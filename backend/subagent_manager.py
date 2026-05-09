"""
Sub-Agent Manager — ad-hoc, in-memory agent lifecycle management.

Sub-agents are spawned by parent agents. They share the parent's configuration
(model, tools, skills, system prompt) but have no DB entries and exist only
in memory. Communication uses the existing agent-to-agent messaging protocol.

Sub-Agent ID convention: {parent_id}_sub_{counter}  (e.g., linus_sub_1)
"""

import threading
import time
import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# Auto-destroy after 10 minutes of idle
_SUBAGENT_IDLE_TTL = 600  # seconds


class SubAgent:
    """In-memory representation of a spawned sub-agent."""

    __slots__ = (
        'id', 'parent_id', 'config', 'created_at', 'last_active_at',
    )

    def __init__(self, sub_id: str, parent_id: str, config: Dict[str, Any]):
        self.id = sub_id
        self.parent_id = parent_id
        self.config = config          # Full agent config dict (as if from DB)
        self.created_at = time.time()
        self.last_active_at = time.time()

    def touch(self) -> None:
        """Mark this sub-agent as recently active."""
        self.last_active_at = time.time()

    def is_expired(self, ttl: float = _SUBAGENT_IDLE_TTL) -> bool:
        """Return True if this sub-agent has been idle beyond TTL."""
        return (time.time() - self.last_active_at) > ttl


class SubAgentManager:
    """Singleton manager for sub-agent lifecycle.

    Sub-agents are purely in-memory. They are NOT stored in the 'agents' DB table.
    They inherit the parent's model, tools, skills, system prompt, and use the
    parent's per-agent chat DB (db_agent_id = parent_id).
    """

    def __init__(self):
        self._lock = threading.Lock()
        # sub_agent_id -> SubAgent
        self._subagents: Dict[str, SubAgent] = {}
        # parent_id -> next counter
        self._counters: Dict[str, int] = {}
        # Cleanup timer
        self._cleanup_timer: Optional[threading.Timer] = None

    def spawn(self, parent_agent: Dict[str, Any]) -> str:
        """Spawn a sub-agent from a parent agent config.

        Args:
            parent_agent: Full agent dict from DB (must have 'id').

        Returns:
            The sub-agent's ID string.

        Raises:
            ValueError: if parent_agent has no 'id'.
        """
        parent_id = parent_agent.get('id', '')
        if not parent_id:
            raise ValueError("parent_agent must have an 'id'")

        with self._lock:
            counter = self._counters.get(parent_id, 0) + 1
            self._counters[parent_id] = counter

        sub_id = f"{parent_id}_sub_{counter}"

        # Build a complete agent config for the sub-agent, inheriting from parent
        config = dict(parent_agent)          # shallow copy is fine for our use
        config['id'] = sub_id
        # A sub-agent is never "super" unless the parent is
        # (is_super is inherited from parent)
        config['is_subagent'] = True
        config['parent_id'] = parent_id
        # Sub-agents use the parent's per-agent chat DB
        config['_db_agent_id'] = parent_id

        sub = SubAgent(sub_id, parent_id, config)

        with self._lock:
            self._subagents[sub_id] = sub

        _logger.info(
            "Sub-agent spawned: %s (parent=%s, counter=%d)",
            sub_id, parent_id, counter,
        )

        # Ensure cleanup is scheduled
        self._ensure_cleanup()

        return sub_id

    def destroy(self, sub_agent_id: str) -> bool:
        """Destroy a sub-agent by ID.

        Archives the sub-agent's sessions in the parent's chat DB and removes
        the in-memory SubAgent object.

        Returns True if the sub-agent existed and was destroyed, False otherwise.
        """
        with self._lock:
            sub = self._subagents.pop(sub_agent_id, None)

        if sub:
            # Archive sessions in parent's DB so they disappear from the sessions page
            try:
                from models.chat import agent_chat_manager
                chat_db = agent_chat_manager.get(sub.parent_id)
                archived = chat_db.archive_sessions_by_agent_id(sub_agent_id)
                if archived:
                    _logger.info("Archived %d session(s) for sub-agent %s", archived, sub_agent_id)
            except Exception as e:
                _logger.warning("Failed to archive sessions for sub-agent %s: %s", sub_agent_id, e)
            _logger.info("Sub-agent destroyed: %s (parent=%s)", sub_agent_id, sub.parent_id)
            return True

        _logger.debug("Sub-agent not found for destroy: %s", sub_agent_id)
        return False

    def get(self, sub_agent_id: str) -> Optional[Dict[str, Any]]:
        """Get a sub-agent's config dict, or None if not found.

        Also touches the sub-agent's last_active_at.
        """
        with self._lock:
            sub = self._subagents.get(sub_agent_id)

        if sub:
            sub.touch()
            return sub.config

        return None

    def is_subagent(self, agent_id: str) -> bool:
        """Check if an agent ID belongs to a sub-agent."""
        with self._lock:
            return agent_id in self._subagents

    def list_subagents(self, parent_id: str) -> List[Dict[str, Any]]:
        """List all live sub-agents for a given parent ID.

        Returns a list of {id, parent_id, created_at, last_active_at} dicts.
        """
        with self._lock:
            subs = [
                {
                    'id': s.id,
                    'parent_id': s.parent_id,
                    'created_at': s.created_at,
                    'last_active_at': s.last_active_at,
                }
                for s in self._subagents.values()
                if s.parent_id == parent_id
            ]

        # Touch all returned sub-agents (listing is activity)
        for s_id in [s['id'] for s in subs]:
            self._touch(s_id)

        return subs

    def destroy_all_for_parent(self, parent_id: str) -> int:
        """Destroy all sub-agents belonging to a parent. Returns count destroyed."""
        with self._lock:
            to_remove = [
                sid for sid, sub in self._subagents.items()
                if sub.parent_id == parent_id
            ]
            for sid in to_remove:
                del self._subagents[sid]

        if to_remove:
            _logger.info(
                "Destroyed %d sub-agents for parent %s: %s",
                len(to_remove), parent_id, ', '.join(to_remove),
            )

        return len(to_remove)

    def _touch(self, sub_agent_id: str) -> None:
        """Touch a sub-agent's last_active_at without requiring it to exist."""
        with self._lock:
            sub = self._subagents.get(sub_agent_id)
        if sub:
            sub.touch()

    # --- Cleanup ---

    def _ensure_cleanup(self) -> None:
        """Schedule the periodic cleanup timer if not already running."""
        with self._lock:
            if self._cleanup_timer is not None:
                return
            self._cleanup_timer = threading.Timer(60.0, self._cleanup_expired)
            self._cleanup_timer.daemon = True
            self._cleanup_timer.start()

    def _cleanup_expired(self) -> None:
        """Periodic cleanup: destroy sub-agents that have been idle beyond TTL."""
        expired = []

        with self._lock:
            for sid, sub in list(self._subagents.items()):
                if sub.is_expired():
                    expired.append(sid)

        for sid in expired:
            self.destroy(sid)

        if expired:
            _logger.info("Cleaned up %d expired sub-agent(s)", len(expired))

        # Reschedule
        with self._lock:
            self._cleanup_timer = threading.Timer(60.0, self._cleanup_expired)
            self._cleanup_timer.daemon = True
            self._cleanup_timer.start()

    def shutdown(self) -> None:
        """Cancel cleanup timer and clear all state. Call during graceful shutdown."""
        with self._lock:
            if self._cleanup_timer:
                self._cleanup_timer.cancel()
                self._cleanup_timer = None
            count = len(self._subagents)
            self._subagents.clear()
            self._counters.clear()
        _logger.info("SubAgentManager shutdown: cleared %d sub-agent(s)", count)


# Global singleton
subagent_manager = SubAgentManager()
