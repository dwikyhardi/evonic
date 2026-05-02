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

    def resolve_target_agent(self, external_user_id: str) -> str | None:
        """Resolve which agent should handle an inbound message from `external_user_id`.

        Two-layer resolution:
          1. Identity override — if `user_channel_identities` has a row for
             (channel_id, external_user_id) that is enabled, has a non-disabled
             parent user, and a non-NULL `agent_id`, route to that agent.
          2. Channel default — otherwise fall back to `channels.agent_id`
             (the channel's default agent), provided that agent still exists.

        Returns None only when the channel itself has no usable default agent
        (operator misconfiguration); in that case the caller drops the message
        with an error log.
        """
        from models.db import db

        # Layer 1: identity override
        try:
            ident = db.resolve_identity(self.channel_id, external_user_id)
        except Exception:
            ident = None
        if ident \
                and ident.get('enabled') \
                and ident.get('user_enabled') != 0 \
                and ident.get('agent_id'):
            return ident['agent_id']

        # Layer 2: channel default agent
        try:
            ch = db.get_channel(self.channel_id)
        except Exception:
            ch = None
        if ch and ch.get('agent_id'):
            try:
                if db.get_agent(ch['agent_id']):
                    return ch['agent_id']
            except Exception:
                pass
        return None

    @property
    def is_running(self) -> bool:
        return self._running
