"""
Agent Runtime package.

Public API (unchanged from the old single-file module):
  - AgentRuntime   — the runtime class
  - agent_runtime  — the global singleton instance
  - DEFAULT_SUMMARIZE_PROMPT — the default summarization prompt template
"""

import logging

from backend.agent_runtime.runtime import AgentRuntime
from backend.agent_runtime.summarizer import DEFAULT_SUMMARIZE_PROMPT

log = logging.getLogger(__name__)

# Global singleton — started once at import time (workers launched in __init__)
agent_runtime = AgentRuntime()


def _on_agent_free_check(event):
    """Scheduler callback: notify a waiting user when their agent becomes free."""
    payload = event.get('payload', {})
    agent_id = payload.get('agent_id')
    if not agent_id:
        log.warning("[AgentFreeCheck] Missing agent_id in payload: %s", payload)
        return

    # Still busy — next tick will check again
    if agent_runtime.is_agent_busy(agent_id):
        log.debug("[AgentFreeCheck] agent=%s is still busy — skipping notification", agent_id)
        return

    session_id = payload.get('session_id')
    external_user_id = payload.get('external_user_id')
    channel_id = payload.get('channel_id')
    if not session_id or not external_user_id:
        log.warning("[AgentFreeCheck] agent=%s missing session_id or external_user_id in payload: %s",
                    agent_id, payload)
        return

    log.info("[AgentFreeCheck] agent=%s is free — sending notification to session=%s user=%s",
             agent_id, session_id, external_user_id)

    from models.db import db
    notify_msg = "Hey! I'm done and ready to help again. Is there anything I can do?"
    try:
        db.add_chat_message(session_id, 'assistant', notify_msg,
                            agent_id=agent_id, metadata={"free_notification": True})
    except Exception as e:
        log.error("[AgentFreeCheck] Failed to save notification message: %s", e)

    # Push SSE event so the web chat UI renders the notification immediately
    try:
        from backend.event_stream import event_stream as _es
        _es.emit('message_received', {
            'agent_id': agent_id,
            'session_id': session_id,
            'external_user_id': external_user_id,
            'channel_id': channel_id,
        })
    except Exception as e:
        log.error("[AgentFreeCheck] Failed to emit message_received event: %s", e)

    # Send via channel if applicable
    if channel_id:
        try:
            from backend.channels.registry import channel_manager
            instance = channel_manager._active.get(channel_id)
            if instance and instance.is_running:
                instance.send_message(external_user_id, notify_msg)
        except Exception as e:
            log.error("[AgentFreeCheck] Failed to send via channel=%s: %s", channel_id, e)

    # Cancel the scheduler — job is done
    try:
        from backend.scheduler import scheduler
        schedule_name = f'agent_free_notify:{agent_id}:{session_id}'
        for s in scheduler.list_schedules(owner_type='agent', owner_id=agent_id):
            if s.get('name') == schedule_name:
                scheduler.cancel_schedule(s['id'])
                log.info("[AgentFreeCheck] Cancelled schedule '%s'", schedule_name)
                break
    except Exception as e:
        log.error("[AgentFreeCheck] Failed to cancel schedule: %s", e)


def _on_summary_updated(event):
    """After summarization, extract and store memorable facts in the background."""
    payload = event.get('payload', {})
    agent_id = payload.get('agent_id')
    session_id = payload.get('session_id')
    summary = payload.get('summary')
    if not (agent_id and session_id and summary):
        return

    import threading
    from backend.agent_runtime.memory_manager import extract_and_store_memories
    from models.db import db

    agent = db.get_agent(agent_id)
    if not agent:
        return

    threading.Thread(
        target=extract_and_store_memories,
        args=(agent, session_id, summary, AgentRuntime._llm_lock),
        daemon=True,
    ).start()


# Register event listeners
try:
    from backend.event_stream import event_stream
    event_stream.on('agent_free_check', _on_agent_free_check)
    event_stream.on('summary_updated', _on_summary_updated)
except Exception:
    pass


__all__ = ['AgentRuntime', 'agent_runtime', 'DEFAULT_SUMMARIZE_PROMPT']
