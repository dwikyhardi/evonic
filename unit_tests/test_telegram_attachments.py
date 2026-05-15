"""Tests for the Telegram channel attachment-ingestion path.

These tests exercise helper functions directly and a slim handler harness that
mirrors the production attachment branch without spinning up the full
python-telegram-bot Application.
"""
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.channels.telegram import (
    _detect_non_photo_attachment,
    _human_size,
    _sanitize_filename,
)
from models.db import db


def _make_agent(agent_id='tg_agent', enabled=1, max_mb=20, supported=1):
    db.create_agent({
        'id': agent_id, 'name': agent_id, 'system_prompt': '',
    })
    model_id = f'model_for_{agent_id}'
    db.create_model({
        'id': model_id, 'name': model_id, 'type': 'openai',
        'provider': 'openai', 'model_name': model_id,
        'attachments_supported': supported,
    })
    with db._connect() as conn:
        conn.execute(
            "UPDATE agents SET attachments_enabled=?, attachment_max_size_mb=?, "
            "default_model_id=? WHERE id=?",
            (enabled, max_mb, model_id, agent_id),
        )
    return agent_id


def _msg_with_document(file_name='invoice.pdf', mime_type='application/pdf',
                       file_size=1024, file_id='tg_doc_1'):
    doc = SimpleNamespace(
        file_id=file_id, file_name=file_name,
        mime_type=mime_type, file_size=file_size,
    )
    return SimpleNamespace(
        document=doc, audio=None, voice=None, video=None,
        video_note=None, animation=None, sticker=None, photo=[],
    )


def _msg_with_voice(file_size=2048, file_id='tg_voice_1'):
    voice = SimpleNamespace(
        file_id=file_id, file_name=None, mime_type=None, file_size=file_size,
    )
    return SimpleNamespace(
        document=None, audio=None, voice=voice, video=None,
        video_note=None, animation=None, sticker=None, photo=[],
    )


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------

def test_sanitize_filename_strips_unsafe():
    # forward slashes are replaced; dots are preserved (allowed char).
    assert _sanitize_filename("../../etc/passwd") == ".._.._etc_passwd"
    assert _sanitize_filename("hello world.pdf") == "hello_world.pdf"
    assert _sanitize_filename("") == 'file'
    # non-ASCII letters are replaced with '_'
    assert _sanitize_filename("ünicode.txt").startswith('_')


def test_sanitize_filename_caps_length():
    name = 'x' * 500 + '.pdf'
    assert len(_sanitize_filename(name)) == 120


def test_human_size_formats():
    # Both ``None`` and a negative size fall back to "0B", but a legitimate
    # zero-byte file MUST render as "0B" too (not be silently coerced via a
    # truthiness check that conflates None and 0).
    assert _human_size(None) == '0B'
    assert _human_size(-1) == '0B'
    assert _human_size(0) == '0B'
    assert _human_size(500) == '500B'
    assert _human_size(2048) == '2.0KB'
    assert _human_size(5 * 1024 * 1024) == '5.0MB'


def test_telegram_default_mime_keys_match_candidates():
    """``_TG_FILE_TYPE_DEFAULT_MIME`` must only contain keys that the
    non-photo candidate gate in ``_detect_non_photo_attachment`` actually
    consults; otherwise the mapping has a dead branch (e.g. an old 'photo'
    key that the photo path never reads).
    """
    from backend.channels.telegram import _TG_FILE_TYPE_DEFAULT_MIME
    # Non-photo candidate types as enumerated inside _detect_non_photo_attachment.
    candidate_types = {
        'document', 'audio', 'voice', 'video',
        'video_note', 'animation', 'sticker',
    }
    assert set(_TG_FILE_TYPE_DEFAULT_MIME.keys()).issubset(candidate_types)
    # 'photo' is owned by the dedicated photo / vision branch and must not
    # appear here — it would be unreachable through the non-photo gate.
    assert 'photo' not in _TG_FILE_TYPE_DEFAULT_MIME


def test_detect_non_photo_attachment_document():
    msg = _msg_with_document()
    result = _detect_non_photo_attachment(msg)
    assert result is not None
    file_id, name, mime, size, ftype = result
    assert file_id == 'tg_doc_1'
    assert name == 'invoice.pdf'
    assert mime == 'application/pdf'
    assert size == 1024
    assert ftype == 'document'


def test_detect_non_photo_attachment_voice_uses_mime_fallback():
    msg = _msg_with_voice()
    result = _detect_non_photo_attachment(msg)
    assert result is not None
    file_id, name, mime, size, ftype = result
    assert ftype == 'voice'
    assert mime == 'audio/ogg'  # fallback when Telegram leaves mime None
    assert name == 'voice.ogg'  # synthesized name


def test_detect_non_photo_attachment_none_for_text_only():
    msg = SimpleNamespace(document=None, audio=None, voice=None, video=None,
                          video_note=None, animation=None, sticker=None, photo=[])
    assert _detect_non_photo_attachment(msg) is None


# ---------------------------------------------------------------------------
# Handler-branch behaviour (DB + filesystem + reply path)
# ---------------------------------------------------------------------------

class _FakeTgFile:
    def __init__(self, body: bytes):
        self._body = body

    async def download_to_drive(self, path):
        with open(path, 'wb') as f:
            f.write(self._body)


def _make_context_bot(body: bytes = b'PDF-DATA'):
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=_FakeTgFile(body))
    return SimpleNamespace(bot=bot)


async def _run_attachment_branch(message, agent_id, session_id, user_id,
                                 channel_id, context, text=''):
    """Mirror the inline attachment-handling branch from telegram.handle_message.

    Returns a dict with side-effect observations.
    """
    from backend.channels.telegram import (
        _detect_non_photo_attachment, _sanitize_filename, _human_size,
    )
    replied = []
    reply_mock = AsyncMock(side_effect=lambda s: replied.append(s))
    message.reply_text = reply_mock

    IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/webp'}
    has_photo = bool(getattr(message, 'photo', None))
    has_image_doc = (
        getattr(message, 'document', None)
        and getattr(message.document, 'mime_type', None) in IMAGE_MIMES
    )
    non_photo = None
    if not has_image_doc:
        non_photo = _detect_non_photo_attachment(message)

    if non_photo:
        file_id, original_filename, mime_type, size_bytes, file_type = non_photo
        cfg = db.get_agent_attachment_config(agent_id)
        if not cfg['enabled'] or not cfg['supported']:
            await message.reply_text("Attachments are not enabled for this assistant.")
            return {'rejected': 'gated', 'replies': replied, 'text': text}
        max_bytes = cfg['max_size_mb'] * 1024 * 1024
        if size_bytes and size_bytes > max_bytes:
            await message.reply_text(f"File too large (max {cfg['max_size_mb']}MB).")
            return {'rejected': 'oversize', 'replies': replied, 'text': text}
        safe = _sanitize_filename(original_filename)
        target_dir = os.path.join('data', 'attachments', agent_id, session_id)
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, f"{int(time.time())}_{safe}")
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(target_path)
        real_size = size_bytes or os.path.getsize(target_path)
        attachment_id = db.save_attachment(
            agent_id=agent_id, session_id=session_id,
            filename=os.path.basename(target_path), file_path=target_path,
            external_user_id=user_id, channel_id=channel_id,
            channel_type='telegram', original_filename=original_filename,
            mime_type=mime_type, file_type=file_type, size_bytes=real_size,
            telegram_file_id=file_id,
        )
        info_line = (
            f"[Attached: {original_filename} "
            f"({mime_type or 'application/octet-stream'}, "
            f"{_human_size(real_size)}) id={attachment_id} path={target_path}]"
        )
        text = info_line + (f"\n{text}" if text else '')
        return {
            'accepted': True,
            'attachment_id': attachment_id,
            'target_path': target_path,
            'text': text,
            'replies': replied,
        }
    return {'no_attachment': True, 'text': text, 'replies': replied}


def _aio_run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_handler_branch_accepts_document(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('tg_doc_ok', enabled=1, supported=1, max_mb=5)
    msg = _msg_with_document(file_size=1024)
    ctx = _make_context_bot(b'BODY')
    out = _aio_run(_run_attachment_branch(
        msg, agent_id='tg_doc_ok', session_id='s1',
        user_id='42', channel_id='tg_ch', context=ctx, text='hello',
    ))
    assert out.get('accepted') is True
    assert out['text'].startswith('[Attached: invoice.pdf')
    assert out['text'].endswith('hello')
    assert os.path.isfile(out['target_path'])
    row = db.get_attachment(out['attachment_id'])
    assert row is not None
    assert row['mime_type'] == 'application/pdf'
    ctx.bot.get_file.assert_awaited_once()


def test_handler_branch_rejects_when_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('tg_doc_off', enabled=0, supported=1)
    msg = _msg_with_document()
    ctx = _make_context_bot()
    out = _aio_run(_run_attachment_branch(
        msg, agent_id='tg_doc_off', session_id='s1',
        user_id='1', channel_id='tg', context=ctx, text='',
    ))
    assert out.get('rejected') == 'gated'
    assert any('not enabled' in r for r in out['replies'])
    ctx.bot.get_file.assert_not_awaited()
    # No attachment row should be persisted.
    assert db.list_session_attachments('s1', 'tg_doc_off') == []


def test_handler_branch_rejects_oversize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('tg_doc_big', enabled=1, supported=1, max_mb=1)
    msg = _msg_with_document(file_size=5 * 1024 * 1024)
    ctx = _make_context_bot()
    out = _aio_run(_run_attachment_branch(
        msg, agent_id='tg_doc_big', session_id='s1',
        user_id='1', channel_id='tg', context=ctx, text='',
    ))
    assert out.get('rejected') == 'oversize'
    assert any('File too large' in r for r in out['replies'])
    ctx.bot.get_file.assert_not_awaited()
    assert db.list_session_attachments('s1', 'tg_doc_big') == []


def test_handler_branch_rejects_when_model_unsupported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('tg_doc_nosup', enabled=1, supported=0)
    msg = _msg_with_document()
    ctx = _make_context_bot()
    out = _aio_run(_run_attachment_branch(
        msg, agent_id='tg_doc_nosup', session_id='s1',
        user_id='1', channel_id='tg', context=ctx, text='',
    ))
    assert out.get('rejected') == 'gated'
    ctx.bot.get_file.assert_not_awaited()
