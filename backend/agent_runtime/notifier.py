"""
notifier.py — Centralized agent notification system.

Provides notify_agent() as the single entry point for all system/plugin
notifications directed at an agent. Handles:
- Tag-prefixed message composition
- Routing resolution (external_user_id + channel_id lookup)
- Deduplication against recent message history
- LLM triggering (trigger_llm=True) or DB-only storage (trigger_llm=False)
"""

from models.db import db
from backend.logging_config import get_logger

_logger = get_logger(__name__)


def notify_agent(agent_id: str, tag: str, message: str,
                 channel_type: str = None,
                 external_user_id: str = None,
                 channel_id: str = None,
                 session_id: str = None,
                 dedup: bool = True,
                 dedup_window: int = 5,
                 trigger_llm: bool = True,
                 metadata: dict = None) -> dict:
    """Send a system notification to an agent.

    Args:
        agent_id: Target agent ID.
        tag: Notification tag without brackets, e.g. "System/Task" or
             "SYSTEM NOTIFICATION". The full message will be prefixed as
             "[{tag}] {message}".
        message: Notification body text (without tag prefix).
        channel_type: Channel type hint for routing resolution, e.g. "telegram".
                      Used when external_user_id/channel_id are not provided.
        external_user_id: Explicit routing — the user ID for the target session.
                          If omitted, auto-resolved from the agent's most recent session.
        channel_id: Explicit routing — the channel UUID. If omitted, auto-resolved.
        session_id: If provided, use this session directly (bypasses routing
                    resolution). Takes precedence over external_user_id/channel_id.
        dedup: If True, skip sending if an identical message already exists in
               the last `dedup_window` messages of the session. Default True.
        dedup_window: Number of recent messages to check for duplicates. Default 5.
        trigger_llm: If True (default), route through handle_message() to trigger
                     the LLM loop. If False, save directly to DB without LLM processing
                     (use for informational notifications like system errors).
        metadata: Optional extra metadata dict merged into the saved message record.

    Returns:
        dict with keys:
          - success (bool)
          - session_id (str or None)
          - reason (str or None): "deduplicated", "no_route", "error", or None on success
    """
    full_message = f"[{tag}] {message}"

    # Resolve routing only when session_id is not provided
    if session_id:
        pass  # Use the provided session_id directly below
    else:
        if not external_user_id:
            resolved_uid, resolved_cid = _resolve_agent_target(agent_id, channel_type)
            if not resolved_uid:
                # Only apply fallback if no explicit routing was provided
                if external_user_id is None:
                    _logger.warning(
                        "notify_agent: no active channel session for agent '%s' "
                        "(channel_type=%s), falling back to web session.",
                        agent_id, channel_type,
                    )
                    external_user_id = f"__system__{agent_id}"
                    channel_id = None
            else:
                external_user_id = resolved_uid
                channel_id = channel_id or resolved_cid

    _logger.info(
        "notify_agent: agent=%s tag=%s trigger_llm=%s external_user_id=%s "
        "channel_id=%s session_id=%s dedup=%s.",
        agent_id, tag, trigger_llm, external_user_id or 'auto',
        channel_id or 'none', session_id or 'auto', dedup,
    )

    try:
        if session_id:
            # Validate session exists and extract its external_user_id / channel_id
            # Uses get_session_with_details for cross-agent lookup (per-agent DBs)
            session_info = db.get_session_with_details(session_id)
            if not session_info:
                _logger.warning(
                    "notify_agent: provided session_id '%s' not found for agent '%s'.",
                    session_id, agent_id,
                )
                return {"success": False, "session_id": None, "reason": "error"}
            external_user_id = session_info.get('external_user_id')
            channel_id = session_info.get('channel_id')
            target_session_id = session_id
        else:
            target_session_id = db.get_or_create_session(agent_id, external_user_id, channel_id)
    except Exception as e:
        _logger.error(
            "notify_agent: failed to get/create session for agent '%s' "
            "(external_user_id=%s, channel_id=%s): %s",
            agent_id, external_user_id, channel_id, e,
        )
        return {"success": False, "session_id": None, "reason": "error"}

    _logger.info(
        "notify_agent: resolved target_session_id='%s' for agent='%s'.",
        target_session_id, agent_id,
    )

    # Deduplication check
    if dedup and _is_duplicate(target_session_id, full_message, dedup_window):
        _logger.info(
            "notify_agent: dedup — skipping duplicate [%s] notification for agent '%s' "
            "in session '%s'.",
            tag, agent_id, target_session_id,
        )
        return {"success": False, "session_id": target_session_id, "reason": "deduplicated"}

    try:
        if trigger_llm:
            _logger.info(
                "notify_agent: triggering LLM for agent='%s' via handle_message "
                "(session='%s', channel=%s).",
                agent_id, target_session_id, channel_id or 'none',
            )
            from backend.agent_runtime import agent_runtime
            agent_runtime.handle_message(
                agent_id, external_user_id, full_message, channel_id,
                metadata=metadata,
            )
        else:
            meta = dict(metadata) if metadata else {}
            db.add_chat_message(
                target_session_id, role='user', content=full_message,
                agent_id=agent_id, metadata=meta if meta else None,
            )
            from backend.event_stream import event_stream
            event_stream.emit('message_received', {
                'agent_id': agent_id,
                'session_id': target_session_id,
                'external_user_id': external_user_id,
                'channel_id': channel_id,
                'message': full_message,
            })
    except Exception as e:
        import traceback as _tb
        _logger.error(
            "notify_agent: failed to notify agent '%s' (session='%s'): %s\n%s",
            agent_id, target_session_id, e, _tb.format_exc(),
        )
        return {"success": False, "session_id": target_session_id, "reason": "error"}

    return {"success": True, "session_id": target_session_id, "reason": None}


def _resolve_agent_target(agent_id: str, channel_type: str = None):
    """Resolve (external_user_id, channel_id) for an agent.

    Priority:
    1. If the agent has a primary_channel_id and it's active → use it
    2. Otherwise, find the most recent active channel session
    3. Optionally filter by channel_type (e.g. "telegram")

    Returns (None, None) if not found.
    """
    try:
        import sqlite3
        from models.db import AgentChatDB
        from backend.channels.registry import channel_manager

        channels = db.get_channels(agent_id)
        active_channel = None

        # Check primary channel first
        primary_cid = db.get_primary_channel_id(agent_id)
        if primary_cid and primary_cid in channel_manager._active:
            for ch in channels:
                if ch['id'] == primary_cid:
                    active_channel = ch
                    break

        if not active_channel:
            # Fallback: find any active channel
            for ch in channels:
                ch_type = ch.get('type', '').lower()
                if channel_type:
                    if ch_type == channel_type.lower() and ch['id'] in channel_manager._active:
                        active_channel = ch
                        break
                else:
                    if ch['id'] in channel_manager._active:
                        active_channel = ch
                        break

        if not active_channel:
            return None, None

        resolved_channel_id = active_channel['id']
        agent_db = AgentChatDB(agent_id)
        with agent_db._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT external_user_id FROM chat_sessions
                WHERE agent_id = ? AND channel_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (agent_id, resolved_channel_id))
            row = cursor.fetchone()

        if not row:
            return None, None

        return row['external_user_id'], resolved_channel_id

    except Exception:
        return None, None


def _is_duplicate(session_id: str, full_message: str, window: int) -> bool:
    """Return True if full_message already appears in the last `window` user messages."""
    try:
        recent = db.get_session_messages(session_id, limit=window)
        return any(
            m.get('role') == 'user' and m.get('content') == full_message
            for m in recent
        )
    except Exception:
        return False
