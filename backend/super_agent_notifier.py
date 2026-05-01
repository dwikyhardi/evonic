"""
Super Agent Notifier

Subscribes to critical platform events and routes them as system notifications
to the super agent's chat session. Rate-limited to prevent flooding.
"""

import logging
import time
import threading
from typing import Dict

from backend.event_stream import event_stream

_logger = logging.getLogger(__name__)
from models.db import db

# Rate limiting: one notification per event category per N seconds
_RATE_LIMIT_SECONDS = 60
_last_notify: Dict[str, float] = {}
_rate_lock = threading.Lock()

# System user ID for notifications
_SYSTEM_USER_ID = '__system__'


def _is_rate_limited(category: str) -> bool:
    now = time.time()
    with _rate_lock:
        last = _last_notify.get(category, 0)
        if now - last < _RATE_LIMIT_SECONDS:
            return True
        _last_notify[category] = now
    return False


def _send_notification(category: str, message: str):
    """Send a notification message to the super agent's system session."""
    if _is_rate_limited(category):
        return
    try:
        super_agent = db.get_super_agent()
        if not super_agent:
            return
        from backend.agent_runtime.notifier import notify_agent
        notify_agent(
            agent_id=super_agent['id'],
            tag='SYSTEM NOTIFICATION',
            message=message,
            external_user_id=_SYSTEM_USER_ID,
            channel_id=None,
            trigger_llm=False,
            dedup=True,
            metadata={'system_notification': True, 'category': category},
        )
    except Exception as e:
        _logger.error("Failed to send notification: %s", e)


def _on_llm_error(data: dict):
    agent_id = data.get('agent_id', 'unknown')
    error_detail = data.get('error_detail', data.get('response', 'Unknown error'))
    _send_notification(
        f"llm_error:{agent_id}",
        f"LLM error on agent **{agent_id}**: {error_detail}"
    )


def _on_tool_executed(data: dict):
    if not data.get('has_error'):
        return
    agent_id = data.get('agent_id', 'unknown')
    tool_name = data.get('tool_name', 'unknown')
    result = data.get('tool_result', {})
    error_msg = result.get('error') if isinstance(result, dict) else str(result)
    _send_notification(
        f"tool_error:{agent_id}:{tool_name}",
        f"Tool error on agent **{agent_id}** — `{tool_name}`: {error_msg}"
    )


def _on_channel_error(data: dict):
    agent_id = data.get('agent_id', 'unknown')
    channel_id = data.get('channel_id', 'unknown')
    error = data.get('error', 'Unknown error')
    _send_notification(
        f"channel_error:{agent_id}:{channel_id}",
        f"Channel error on agent **{agent_id}** (channel `{channel_id}`): {error}"
    )


def _on_system_error(data: dict):
    component = data.get('component', 'unknown')
    error = data.get('error', 'Unknown error')
    _send_notification(
        f"system_error:{component}",
        f"System error in **{component}**: {error}"
    )


def init_super_agent_notifier():
    """Subscribe to critical events. Call once at app startup."""
    # Tool execution errors
    event_stream.on('tool_executed', _on_tool_executed)
    # Channel errors (emitted by channel implementations)
    event_stream.on('channel_error', _on_channel_error)
    # Generic system errors (can be emitted by any component)
    event_stream.on('system_error', _on_system_error)
    _logger.info("Initialized — subscribed to critical events.")
