from typing import Dict, Any, List, Optional


class ChatDelegationMixin:
    """Chat session delegation to per-agent AgentChatDB instances.
    Requires self._connect(), self.get_agents(), self.get_agent(), self.get_channel()
    from the host class."""

    def _chat_db(self, agent_id: str) -> 'AgentChatDB':
        from models.chat import agent_chat_manager
        return agent_chat_manager.get(agent_id)

    def get_or_create_session(self, agent_id: str, external_user_id: str,
                               channel_id: str = None) -> str:
        channel_type = None
        if channel_id:
            ch = self.get_channel(channel_id)
            channel_type = ch.get('type') if ch else None
        return self._chat_db(agent_id).get_or_create_session(
            agent_id, external_user_id, channel_id, channel_type=channel_type)

    def get_session_messages(self, session_id: str, limit: int = 50,
                              agent_id: str = None) -> List[Dict[str, Any]]:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return []
        return self._chat_db(agent_id).get_session_messages(session_id, limit)

    def add_chat_message(self, session_id: str, role: str, content: str = None,
                          tool_calls: Any = None, tool_call_id: str = None,
                          agent_id: str = None, metadata: dict = None) -> int:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return -1
        result = self._chat_db(agent_id).add_chat_message(session_id, role, content, tool_calls, tool_call_id, metadata=metadata)
        # Update last_active_at in main agents table
        try:
            with self._connect() as conn:
                conn.execute("UPDATE agents SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (agent_id,))
                conn.commit()
        except Exception:
            pass
        return result

    def touch_agent_active(self, agent_id: str) -> None:
        """Update last_active_at on the agents table."""
        try:
            with self._connect() as conn:
                conn.execute("UPDATE agents SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (agent_id,))
                conn.commit()
        except Exception:
            pass

    def upsert_agent_state(self, content: str, agent_id: str):
        self._chat_db(agent_id).upsert_agent_state(content)

    def get_agent_state(self, agent_id: str) -> str | None:
        return self._chat_db(agent_id).get_agent_state()

    def clear_session(self, session_id: str, agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if agent_id:
            self._chat_db(agent_id).clear_session(session_id)
            from models.chatlog import chatlog_manager
            chatlog_manager.get(agent_id, session_id).clear()

    def get_summary(self, session_id: str, agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return None
        return self._chat_db(agent_id).get_summary(session_id)

    def upsert_summary(self, session_id: str, summary: str,
                        last_message_id: int, message_count: int,
                        agent_id: str = None, last_message_ts: int = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if agent_id:
            self._chat_db(agent_id).upsert_summary(
                session_id, summary, last_message_id, message_count,
                last_message_ts=last_message_ts)

    def get_messages_after(self, session_id: str, after_id: int,
                            agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return []
        return self._chat_db(agent_id).get_messages_after(session_id, after_id)

    def get_messages_between(self, session_id: str, after_id: int,
                              up_to_id: int, agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return []
        return self._chat_db(agent_id).get_messages_between(session_id, after_id, up_to_id)

    def get_message_count(self, session_id: str, agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return 0
        return self._chat_db(agent_id).get_message_count(session_id)

    def delete_session(self, session_id: str, agent_id: str = None) -> bool:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return False
        result = self._chat_db(agent_id).delete_session(session_id)
        if result:
            import os
            from models.chatlog import chatlog_manager
            cl = chatlog_manager.get(agent_id, session_id)
            cl.close()
            chatlog_manager.evict(agent_id, session_id)
            try:
                os.remove(cl._path)
            except FileNotFoundError:
                pass
        return result

    def get_session_messages_full(self, session_id: str, agent_id: str = None) -> List[Dict[str, Any]]:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return []
        return self._chat_db(agent_id).get_session_messages_full(session_id)

    def get_new_messages(self, session_id: str, after_id: int, agent_id: str = None) -> List[Dict[str, Any]]:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return []
        return self._chat_db(agent_id).get_new_messages(session_id, after_id)

    def get_last_assistant_message(self, session_id: str, agent_id: str = None) -> Optional[Dict[str, Any]]:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return None
        return self._chat_db(agent_id).get_last_assistant_message(session_id)

    def set_session_bot_enabled(self, session_id: str, enabled: bool, agent_id: str = None):
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if agent_id:
            self._chat_db(agent_id).set_session_bot_enabled(session_id, enabled)

    def is_session_bot_enabled(self, session_id: str, agent_id: str = None) -> bool:
        agent_id = agent_id or self._find_agent_for_session(session_id)
        if not agent_id:
            return True
        return self._chat_db(agent_id).is_session_bot_enabled(session_id)

    def get_latest_human_session(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._chat_db(agent_id).get_latest_human_session(agent_id)

    def get_session_with_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Find session across all agent DBs and enrich with agent/channel info."""
        agent_id = self._find_agent_for_session(session_id)
        if not agent_id:
            return None
        session = self._chat_db(agent_id).get_session(session_id)
        if not session:
            return None
        # Enrich with agent and channel info from main DB
        agent = self.get_agent(agent_id)
        session['agent_name'] = agent['name'] if agent else 'Unknown'
        if session.get('channel_id'):
            ch = self.get_channel(session['channel_id'])
            session['channel_type'] = ch.get('type') if ch else None
            session['channel_name'] = ch.get('name') if ch else None
        else:
            session['channel_type'] = None
            session['channel_name'] = None
        return session

    def get_all_sessions(self, search: str = None, limit: int = 50, offset: int = 0,
                          exclude_test: bool = True) -> List[Dict[str, Any]]:
        """Aggregate sessions across all per-agent chat DBs."""
        agents = self.get_agents()
        all_sessions = []
        for agent in agents:
            chat_db = self._chat_db(agent['id'])
            sessions = chat_db.get_sessions_with_preview()
            for s in sessions:
                s['agent_name'] = agent.get('name', 'Unknown')
                # Enrich channel info
                if s.get('channel_id'):
                    ch = self.get_channel(s['channel_id'])
                    s['channel_type'] = ch.get('type') if ch else None
                    s['channel_name'] = ch.get('name') if ch else None
                else:
                    s['channel_type'] = None
                    s['channel_name'] = None
            all_sessions.extend(sessions)
        # Enrich agent-to-agent sessions with peer agent name
        agent_map = {a['id']: a.get('name', 'Unknown') for a in agents}
        for s in all_sessions:
            euid = s.get('external_user_id', '')
            if euid.startswith('__agent__'):
                peer_agent_id = euid[len('__agent__'):]
                peer_name = agent_map.get(peer_agent_id)
                if peer_name:
                    s['peer_agent_name'] = peer_name
        # Filter out test chat sessions (web_test user with no channel)
        if exclude_test:
            all_sessions = [s for s in all_sessions
                            if not (s.get('external_user_id') == 'web_test'
                                    and not s.get('channel_id'))]
        # Filter by search
        if search:
            q = search.lower()
            all_sessions = [s for s in all_sessions
                            if q in (s.get('agent_name') or '').lower()
                            or q in (s.get('external_user_id') or '').lower()
                            or q in (s.get('peer_agent_name') or '').lower()]
        # Sort by updated_at descending
        all_sessions.sort(key=lambda s: s.get('updated_at') or '', reverse=True)
        total = len(all_sessions)
        if limit > 0:
            all_sessions = all_sessions[offset:offset + limit]
        else:
            all_sessions = []
        return all_sessions, total

    def _find_agent_for_session(self, session_id: str) -> Optional[str]:
        """Look up which agent owns a session by scanning agent chat DBs."""
        agents = self.get_agents()
        for agent in agents:
            chat_db = self._chat_db(agent['id'])
            if chat_db.has_session(session_id):
                return agent['id']
        return None

    def clear_all_sessions(self):
        """Drop all chat sessions, messages, and summaries across all agents."""
        agents = self.get_agents()
        for agent in agents:
            chat_db = self._chat_db(agent['id'])
            chat_db.clear_all()

    # ---- Long-term Memory delegation ----

    def add_memory(self, agent_id: str, content: str, category: str = 'general',
                   source_session_id: str = None) -> int:
        return self._chat_db(agent_id).add_memory(content, category, source_session_id)

    def update_memory(self, agent_id: str, memory_id: int, content: str,
                      category: str = None):
        self._chat_db(agent_id).update_memory(memory_id, content, category)

    def search_memories(self, agent_id: str, query: str,
                        limit: int = 10) -> List[Dict[str, Any]]:
        return self._chat_db(agent_id).search_memories(query, limit)

    def get_all_memories(self, agent_id: str,
                         include_expired: bool = False) -> List[Dict[str, Any]]:
        return self._chat_db(agent_id).get_all_memories(include_expired)

    def get_recent_memories(self, agent_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self._chat_db(agent_id).get_recent_memories(limit)

    def expire_memory(self, agent_id: str, memory_id: int):
        self._chat_db(agent_id).expire_memory(memory_id)
