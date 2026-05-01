"""Telegram channel implementation using python-telegram-bot."""

import base64
import logging
import re
import time
import threading
from typing import Dict, Any
from backend.channels.base import BaseChannel, strip_system_tags

_logger = logging.getLogger(__name__)


def _strip_markdown(text: str) -> str:
    """Remove markdown symbols (bold, italic, headers) from text for plain Telegram messages."""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # headers
    text = re.sub(r'\*+', '', text)  # bold/italic
    return text


def _split_message(text: str, max_len: int = 4050) -> list:
    """Split text into chunks that fit within Telegram's 4096 char limit.

    Prefers splitting at paragraph breaks, then line breaks, then spaces.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try splitting at paragraph boundary, then line, then space
        split_at = -1
        for sep in ('\n\n', '\n', ' '):
            pos = text.rfind(sep, 0, max_len)
            if pos > 0:
                split_at = pos
                break

        if split_at <= 0:
            split_at = max_len  # hard cut

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip('\n')  # strip leading newlines from next chunk

    return chunks


class TelegramChannel(BaseChannel):
    def __init__(self, channel_id: str, agent_id: str, config: Dict[str, Any]):
        super().__init__(channel_id, agent_id, config)
        self._app = None
        self._thread = None
        self._loop = None  # the event loop owned by the polling thread
        self._approval_required_handler = None
        self._approval_resolved_handler = None

    @staticmethod
    def get_channel_type() -> str:
        return 'telegram'

    def get_system_instructions(self) -> str | None:
        return (
            "IMPORTANT — Telegram Formatting Constraint:\n"
            "You are responding via Telegram which uses PLAIN TEXT only. "
            "Markdown formatting (bold, italic, code blocks, headers, bullet lists, "
            "blockquotes, inline code, links) is NOT supported and will appear as "
            "raw symbols, making your response unreadable.\n\n"
            "STRICTLY FOLLOW THESE RULES:\n"
            "- NEVER use markdown symbols: **, *, `, ```, #, -, >, [], ()\n"
            "- Use UPPERCASE for emphasis instead of bold/italic\n"
            "- Use numbered lists (1. 2. 3.) for lists\n"
            "- Use indentation with spaces for structure\n"
            "- Use plain URLs without markdown link syntax\n"
            "- Write code inline with clear labels like \"CODE:\" prefix\n"
            "- Keep responses clean and readable in plain text"
        )

    def start(self):
        try:
            from telegram import Update
            from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
        except ImportError:
            raise RuntimeError("python-telegram-bot not installed. Run: pip install python-telegram-bot")

        bot_token = self.config.get('bot_token', '')
        if not bot_token:
            raise ValueError("Bot token is required for Telegram channel.")

        from backend.agent_runtime import agent_runtime

        channel_id = self.channel_id
        agent_id = self.agent_id

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message:
                return

            try:
                user_id = str(update.message.chat_id)
                text = strip_system_tags(update.message.text or update.message.caption or '')
                image_url = None

                # Handle photo/image messages if agent has vision enabled
                IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/webp'}
                has_photo = update.message.photo
                has_image_doc = (
                    update.message.document
                    and update.message.document.mime_type in IMAGE_MIMES
                )

                if has_photo or has_image_doc:
                    from models.db import db
                    agent = db.get_agent(agent_id)
                    if agent and agent.get('vision_enabled'):
                        if has_photo:
                            photo = update.message.photo[-1]
                            file = await context.bot.get_file(photo.file_id)
                        else:
                            doc = update.message.document
                            file = await context.bot.get_file(doc.file_id)
                        img_bytes = await file.download_as_bytearray()
                        # Convert to JPEG for consistent LLM input
                        from io import BytesIO
                        from PIL import Image
                        img = Image.open(BytesIO(bytes(img_bytes)))
                        if img.mode in ('RGBA', 'LA', 'P'):
                            img = img.convert('RGB')
                        buf = BytesIO()
                        img.save(buf, format='JPEG', quality=85)
                        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                        image_url = f"data:image/jpeg;base64,{b64}"
                    else:
                        if not text:
                            return
                elif not text:
                    return

                from models.db import db
                session_id = db.get_or_create_session(agent_id, user_id, channel_id)

                # Check if bot is enabled for this session
                if not db.is_session_bot_enabled(session_id, agent_id=agent_id):
                    db.add_chat_message(session_id, 'user', text or '[Image]', agent_id=agent_id)
                    return

                # Detect reply/quote: include replied message content as context
                final_text = text
                reply_to = update.message.reply_to_message
                if reply_to is not None:
                    try:
                        # Check if the replied message is from our bot
                        bot_info = await context.bot.get_me()
                        if reply_to.from_user and reply_to.from_user.id == bot_info.id:
                            # Bot message — include as context
                            replied_text = reply_to.text or reply_to.caption or ''
                            if replied_text:
                                final_text = f"[Replying to: {replied_text[:200]}]\n{text}"
                            else:
                                # Replied to a photo/document from bot
                                final_text = f"[Replying to: (media from bot)]\n{text}"
                        elif reply_to.from_user and reply_to.from_user.id == update.message.chat_id:
                            # User replying to their own previous message
                            replied_text = reply_to.text or reply_to.caption or ''
                            if replied_text:
                                final_text = f"[Replying to myself: {replied_text[:200]}]\n{text}"
                    except Exception:
                        pass  # Silently skip if we can't resolve the reply

                result = agent_runtime.handle_message(
                    agent_id, user_id, final_text, channel_id, image_url=image_url
                )
                if result.get('buffered'):
                    return  # message buffered, response will come from the first caller
                response = _strip_markdown(result.get('response') or '')
                if response and response != "(No response)":
                    # Don't quote slash commands — Telegram's reply preview would show the
                    # user's /command text, which is noisy and unnecessary.
                    is_cmd = text.lstrip().startswith('/')
                    reply_kwargs = {} if is_cmd else {'reply_to_message_id': update.message.message_id}
                    for chunk in _split_message(response):
                        await update.message.reply_text(chunk, **reply_kwargs)
                from backend.event_stream import event_stream
                event_stream.emit('message_sent', {
                    'channel_type': 'telegram',
                    'channel_id': channel_id,
                    'external_user_id': user_id,
                    'message': response,
                })
            except Exception as e:
                _logger.error("Error handling message from chat %s: %s",
                              update.message.chat_id, e, exc_info=True)
                try:
                    await update.message.reply_text(
                        "Sorry, an error occurred while processing your message. "
                        "Please try again.")
                except Exception:
                    pass

        self._app = ApplicationBuilder().token(bot_token).build()
        # Handle text, photos, and image documents (PNG, WebP)
        # Note: we intentionally do NOT exclude COMMAND filter so that
        # slash commands (/clear, /help, /summary) reach our backend handler.
        self._app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message))

        # Inline keyboard callback for approval decisions
        from telegram.ext import CallbackQueryHandler
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            raw = query.data or ''
            parts = raw.split(':', 1)
            if len(parts) != 2 or parts[0] not in ('approve', 'reject'):
                return
            decision, approval_id = parts[0], parts[1]
            from backend.agent_runtime.approval import approval_registry
            # Pop the pending message BEFORE resolve so the async approval_resolved
            # event handler (fired by run_tool_loop) always sees an empty dict and
            # skips its redundant edit — prevents race between two edit_message_text calls.
            _pending_approval_msgs.pop(approval_id, None)
            success = approval_registry.resolve(approval_id, decision)
            label = 'Approved' if decision == 'approve' else 'Rejected'
            if success:
                await query.edit_message_text(f"{label} by user.")
            else:
                await query.edit_message_text("This approval has already been resolved or expired.")

        self._app.add_handler(CallbackQueryHandler(handle_callback))

        # EventStream listener: send inline keyboard when approval is needed for this channel
        from backend.event_stream import event_stream

        _pending_approval_msgs: dict = {}  # approval_id -> (chat_id, message_id)

        def _on_approval_required(data):
            if data.get('channel_id') != channel_id:
                return
            user_id = data.get('external_user_id')
            if not user_id:
                return
            approval_id = data.get('approval_id', '')
            tool_name = data.get('tool_name', '')
            info = data.get('approval_info', {})
            reasons = data.get('reasons', [])
            risk = info.get('risk_level', 'medium')
            desc = info.get('description', 'This action requires careful consideration.')
            reasons_str = ', '.join(reasons) if reasons else '-'
            tool_args = data.get('tool_args') or {}
            code_snippet = tool_args.get('script') or tool_args.get('code') or ''
            code_lang = 'bash' if 'script' in tool_args else 'python'
            if code_snippet and len(code_snippet) > 500:
                code_snippet = code_snippet[:500] + '\n... (truncated)'
            code_block = f"\n\n```{code_lang}\n{code_snippet}\n```" if code_snippet else ''
            source_agent = data.get('source_agent_name')
            header = f"\u26a0\ufe0f Approval Required(agent: {source_agent})" if source_agent else "\u26a0\ufe0f Approval Required"
            text = (
                f"{header}\n"
                f"Tool: {tool_name}\n"
                f"Risk: {risk}\n"
                f"{desc}\n"
                f"Reasons: {reasons_str}"
                f"{code_block}"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject:{approval_id}"),
            ]])
            try:
                sent_msg = self._run_async(
                    self._app.bot.send_message(
                        chat_id=int(user_id), text=text, reply_markup=keyboard
                    )
                )
                _pending_approval_msgs[approval_id] = (int(user_id), sent_msg.message_id)
            except Exception as e:
                _logger.error("Failed to send approval prompt: %s", e)

        def _on_approval_resolved(data):
            if data.get('channel_id') != channel_id:
                return
            approval_id = data.get('approval_id', '')
            msg_info = _pending_approval_msgs.pop(approval_id, None)
            if not msg_info:
                return
            chat_id, message_id = msg_info
            timed_out = data.get('timed_out', False)
            decision = data.get('decision', 'reject')
            if timed_out:
                label = 'Timed out — auto-rejected.'
            elif decision == 'approve':
                label = 'Approved.'
            else:
                label = 'Rejected.'
            try:
                self._run_async(
                    self._app.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id, text=label
                    )
                )
            except Exception:
                pass

        self._approval_required_handler = _on_approval_required
        self._approval_resolved_handler = _on_approval_resolved
        event_stream.on('approval_required', _on_approval_required)
        event_stream.on('approval_resolved', _on_approval_resolved)

        # Typing status listener: send typing indicator on llm_thinking events
        _typing_last_sent: dict = {}  # external_user_id -> timestamp (debounce 3s)

        def _on_llm_thinking(data):
            if data.get('channel_id') != channel_id:
                return
            user_id = data.get('external_user_id')
            if not user_id:
                return
            now = time.time()
            last = _typing_last_sent.get(user_id, 0)
            if now - last < 3:
                return
            _typing_last_sent[user_id] = now
            try:
                self.send_typing(user_id)
            except Exception:
                pass

        self._llm_thinking_handler = _on_llm_thinking
        event_stream.on('llm_thinking', _on_llm_thinking)

        def run_polling():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop  # save reference so send_message/send_typing can use it
            loop.run_until_complete(self._app.initialize())
            loop.run_until_complete(self._app.start())
            loop.run_until_complete(self._app.updater.start_polling())
            self._running = True
            loop.run_forever()

        self._thread = threading.Thread(target=run_polling, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        if not self._running:
            return
        self._running = False
        from backend.event_stream import event_stream
        if self._approval_required_handler:
            event_stream.off('approval_required', self._approval_required_handler)
        if self._approval_resolved_handler:
            event_stream.off('approval_resolved', self._approval_resolved_handler)
        if self._llm_thinking_handler:
            event_stream.off('llm_thinking', self._llm_thinking_handler)
        import asyncio
        loop = self._loop
        if loop and loop.is_running():
            async def _shutdown():
                try:
                    await self._app.updater.stop()
                    await self._app.stop()
                    await self._app.shutdown()
                finally:
                    loop.stop()
            asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        # Wait for the polling thread to exit (up to 10s)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _run_async(self, coro):
        """Run a coroutine on the bot's event loop from any thread."""
        import asyncio
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=10)
        # Fallback: loop not ready yet (shouldn't normally happen)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _do_send(self, external_user_id: str, text: str):
        if not self._app:
            return
        text = _strip_markdown(text)
        for chunk in _split_message(text):
            self._run_async(self._app.bot.send_message(chat_id=external_user_id, text=chunk))
        from backend.event_stream import event_stream
        event_stream.emit('message_sent', {
            'channel_type': 'telegram',
            'channel_id': self.channel_id,
            'external_user_id': external_user_id,
            'message': text,
        })

    def send_typing(self, external_user_id: str):
        if not self._app:
            return
        self._run_async(self._app.bot.send_chat_action(chat_id=external_user_id, action='typing'))
