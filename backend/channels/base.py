"""Base channel abstraction."""

import re
import time
import threading
from abc import ABC, abstractmethod
from threading import Timer
from typing import Dict, Any

_SYSTEM_TAG_RE = re.compile(r'\[(?:SYSTEM(?:/[^\]]*)?|System/[^\]]*)\]\s*')


def strip_system_tags(text: str) -> str:
    """Remove SYSTEM tags from user-supplied channel messages to prevent impersonation."""
    return _SYSTEM_TAG_RE.sub('', text).strip()


class BaseChannel(ABC):
    def __init__(self, channel_id: str, agent_id: str, config: Dict[str, Any]):
        self.channel_id = channel_id
        self.agent_id = agent_id
        self.config = config
        self._running = False

        # Load outbound buffer window from agent config
        try:
            from models.db import db
            agent = db.get_agent(agent_id)
            self._outbound_buffer_seconds = float(
                agent.get('outbound_buffer_seconds', 1.5) if agent else 1.5
            )
        except Exception:
            self._outbound_buffer_seconds = 1.5

        # Outbound coalescing buffer state (per external_user_id)
        self._buf: Dict[str, str] = {}
        self._buf_timers: Dict[str, Timer] = {}
        self._buf_lock = threading.Lock()
        self._last_sent: Dict[str, float] = {}

    @abstractmethod
    def start(self):
        """Start listening for messages."""
        pass

    @abstractmethod
    def stop(self):
        """Stop listening."""
        pass

    def send_message_buffered(self, external_user_id: str, text: str):
        """Coalescing path: accumulate text, reset debounce timer, flush after window.

        Use this for high-frequency intermediate responses to avoid flooding the
        channel provider. Multiple calls within `outbound_buffer_seconds` are merged
        into a single message.
        """
        with self._buf_lock:
            if external_user_id in self._buf:
                self._buf[external_user_id] += "\n\n" + text
            else:
                self._buf[external_user_id] = text
            # Cancel existing timer and start a fresh one
            old = self._buf_timers.pop(external_user_id, None)
            if old:
                old.cancel()
            t = Timer(self._outbound_buffer_seconds, self._flush_buffer, args=[external_user_id])
            t.daemon = True
            self._buf_timers[external_user_id] = t
            t.start()

    def _flush_buffer(self, external_user_id: str):
        """Timer callback: send accumulated text, respecting the rate limit."""
        with self._buf_lock:
            text = self._buf.pop(external_user_id, None)
            self._buf_timers.pop(external_user_id, None)
        if not text:
            return
        # Rate limiter: ensure minimum interval between sends for this chat
        now = time.time()
        last = self._last_sent.get(external_user_id, 0)
        wait = self._outbound_buffer_seconds - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._do_send(external_user_id, text)
        self._last_sent[external_user_id] = time.time()

    def send_message(self, external_user_id: str, text: str):
        """Immediate path: cancel any pending buffer for this chat, merge + send now.

        Use this for final responses and bot-initiated messages. Flushes any
        buffered intermediate content into the same message to avoid split delivery.
        """
        with self._buf_lock:
            pending = self._buf.pop(external_user_id, None)
            old = self._buf_timers.pop(external_user_id, None)
            if old:
                old.cancel()
        if pending:
            text = pending + "\n\n" + text
        self._do_send(external_user_id, text)
        self._last_sent[external_user_id] = time.time()

    @abstractmethod
    def _do_send(self, external_user_id: str, text: str):
        """Actual delivery implementation — subclasses must implement this."""
        pass

    def send_typing(self, external_user_id: str):
        """Send a typing indicator to a user. Optional — no-op by default."""
        pass

    @staticmethod
    @abstractmethod
    def get_channel_type() -> str:
        """Return the channel type identifier (e.g., 'telegram')."""
        pass

    def get_system_instructions(self) -> str | None:
        """Hook for subclasses to inject channel-specific instructions before LLM call.

        Return a string to insert as a system message, or None for no injection.
        """
        return None

    def _check_allowlist(self, external_user_id: str, user_name: str | None = None) -> tuple:
        """Check if user is allowed to chat. Returns (allowed: bool, pair_code: str|None).

        In 'restricted' mode (default for new channels), unregistered users get
        a pairing code that an admin must approve. In 'open' mode, everyone is allowed.
        """
        from models.db import db
        from datetime import datetime, timedelta

        channel = db.get_channel(self.channel_id)
        if not channel:
            return True, None

        # is_user_allowed handles both 'open' mode (always True) and allowlist check
        if db.is_user_allowed(self.channel_id, external_user_id):
            return True, None

        # Generate pairing code and create pending approval (expires in 5 min)
        pair_code = db._generate_pair_code()
        expires_at = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        db.create_pending_approval(
            channel_id=self.channel_id,
            external_user_id=external_user_id,
            user_name=user_name,
            pair_code=pair_code,
            expires_at=expires_at,
        )
        return False, pair_code

    @property
    def is_running(self) -> bool:
        return self._running
