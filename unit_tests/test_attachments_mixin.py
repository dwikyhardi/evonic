"""Unit tests for AttachmentsMixin (CRUD, cleanup, config resolution)."""
import os
import time
import sqlite3
import pytest
from models.db import db


def _make_agent(agent_id='att_agent', model_id=None,
                attachments_enabled=1, max_size_mb=20):
    db.create_agent({
        'id': agent_id,
        'name': agent_id,
        'system_prompt': '',
    })
    # Apply attachment columns + default model directly (update_agent does not
    # accept default_model_id).
    with db._connect() as conn:
        conn.execute(
            "UPDATE agents SET attachments_enabled = ?, attachment_max_size_mb = ?, "
            "default_model_id = ? WHERE id = ?",
            (attachments_enabled, max_size_mb, model_id, agent_id),
        )
    return agent_id


def _make_model(model_id='m1', attachments_supported=1, is_default=0):
    db.create_model({
        'id': model_id,
        'name': model_id,
        'type': 'openai',
        'provider': 'openai',
        'model_name': model_id,
        'attachments_supported': attachments_supported,
        'is_default': is_default,
    })
    return model_id


def _write_file(tmp_path, name='hello.txt', body=b'hi'):
    p = tmp_path / name
    p.write_bytes(body)
    return str(p)


def test_save_and_get_attachment(tmp_path):
    _make_agent()
    path = _write_file(tmp_path)
    aid = db.save_attachment(
        agent_id='att_agent',
        session_id='s1',
        filename='hello.txt',
        file_path=path,
        original_filename='hello.txt',
        mime_type='text/plain',
        file_type='document',
        size_bytes=2,
        channel_type='telegram',
        telegram_file_id='tg_xyz',
    )
    assert isinstance(aid, int) and aid > 0
    row = db.get_attachment(aid)
    assert row is not None
    assert row['agent_id'] == 'att_agent'
    assert row['session_id'] == 's1'
    assert row['mime_type'] == 'text/plain'
    assert row['telegram_file_id'] == 'tg_xyz'
    assert row['file_path'] == path


def test_list_session_attachments(tmp_path):
    _make_agent()
    p1 = _write_file(tmp_path, 'a.txt')
    p2 = _write_file(tmp_path, 'b.txt')
    a1 = db.save_attachment(agent_id='att_agent', session_id='s1',
                            filename='a.txt', file_path=p1)
    a2 = db.save_attachment(agent_id='att_agent', session_id='s1',
                            filename='b.txt', file_path=p2)
    db.save_attachment(agent_id='att_agent', session_id='s2',
                       filename='c.txt', file_path=p2)
    rows = db.list_session_attachments('s1', 'att_agent')
    ids = {r['id'] for r in rows}
    assert ids == {a1, a2}


def test_delete_attachment_removes_row_and_file(tmp_path):
    _make_agent()
    path = _write_file(tmp_path)
    aid = db.save_attachment(agent_id='att_agent', session_id='s1',
                             filename='hello.txt', file_path=path)
    assert os.path.isfile(path)
    assert db.delete_attachment(aid) is True
    assert db.get_attachment(aid) is None
    assert not os.path.exists(path)


def test_delete_attachment_missing_returns_false():
    _make_agent()
    assert db.delete_attachment(9999) is False


def test_cleanup_expired_attachments(tmp_path):
    _make_agent()
    p_old = _write_file(tmp_path, 'old.txt', b'OLD')
    p_new = _write_file(tmp_path, 'new.txt', b'NEW')
    old_id = db.save_attachment(agent_id='att_agent', session_id='s1',
                                filename='old.txt', file_path=p_old, size_bytes=3)
    new_id = db.save_attachment(agent_id='att_agent', session_id='s1',
                                filename='new.txt', file_path=p_new, size_bytes=3)
    # Backdate old row to 10 days ago.
    with db._connect() as conn:
        conn.execute(
            "UPDATE attachments SET created_at = datetime('now', '-10 days') WHERE id = ?",
            (old_id,),
        )
    deleted, freed = db.cleanup_expired_attachments(max_age_days=7)
    assert deleted == 1
    assert freed == 3
    assert db.get_attachment(old_id) is None
    assert db.get_attachment(new_id) is not None
    assert not os.path.exists(p_old)
    assert os.path.exists(p_new)


def test_get_agent_attachment_config_resolves_via_default_model():
    _make_model('m_attach', attachments_supported=1)
    _make_agent(agent_id='ag_a', model_id='m_attach',
                attachments_enabled=1, max_size_mb=15)
    cfg = db.get_agent_attachment_config('ag_a')
    assert cfg['enabled'] is True
    assert cfg['supported'] is True
    assert cfg['max_size_mb'] == 15
    assert cfg['model_id'] == 'm_attach'


def test_get_agent_attachment_config_falls_back_to_global_default():
    _make_model('m_global', attachments_supported=0, is_default=1)
    _make_agent(agent_id='ag_b', model_id=None, attachments_enabled=1)
    cfg = db.get_agent_attachment_config('ag_b')
    assert cfg['enabled'] is True
    assert cfg['supported'] is False  # global default has it off
    assert cfg['model_id'] == 'm_global'


def test_get_agent_attachment_config_caps_max_size_to_20():
    _make_agent(agent_id='ag_c', attachments_enabled=1, max_size_mb=100)
    cfg = db.get_agent_attachment_config('ag_c')
    assert cfg['max_size_mb'] == 20


def test_get_agent_attachment_config_unknown_agent():
    cfg = db.get_agent_attachment_config('does_not_exist')
    assert cfg == {'enabled': False, 'max_size_mb': 20, 'supported': False, 'model_id': None}
