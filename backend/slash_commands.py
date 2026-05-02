"""Slash command registry and executor for agent sessions.

Commands are parsed and executed in the backend so they work on all channels
(Telegram, web, etc.) without any frontend-specific logic.
"""

import logging
import re
import os
import sys
import threading
from typing import Optional, Dict, Any, Callable, Tuple

_logger = logging.getLogger(__name__)

# Command handler signature: (session_id, agent_id, external_user_id, channel_id) -> str
CommandHandler = Callable[[str, str, str, Optional[str]], str]


class SlashCommand:
    """Represents a single slash command."""

    def __init__(self, name: str, handler: CommandHandler, description: str = ""):
        self.name = name
        self.handler = handler
        self.description = description


class SlashCommandRegistry:
    """Registry for slash commands. Supports dynamic registration."""

    def __init__(self):
        self._commands: Dict[str, SlashCommand] = {}

    def register(self, name: str, handler: CommandHandler, description: str = ""):
        """Register a command handler."""
        self._commands[name] = SlashCommand(name, handler, description)

    def get(self, name: str) -> Optional[SlashCommand]:
        """Get a command by name."""
        return self._commands.get(name)

    def list_commands(self) -> list:
        """Return list of (name, description) tuples."""
        return [(cmd.name, cmd.description) for cmd in self._commands.values()]


# Global registry instance
command_registry = SlashCommandRegistry()


def parse_command(message: str) -> Optional[Tuple[str, str]]:
    """Parse a message and extract command + args if it starts with /.

    Returns (command_name, args_string) or None if not a command.
    """
    if not message or not message.startswith("/"):
        return None

    # Match /command or /command args
    match = re.match(r"^/(\w+)(?:\s+(.*))?$", message.strip(), re.DOTALL)
    if not match:
        return None

    cmd_name = match.group(1).lower()
    args = match.group(2) or ""
    return (cmd_name, args)


def execute_command(
    cmd_name: str,
    args: str,
    session_id: str,
    agent_id: str,
    external_user_id: str,
    channel_id: Optional[str] = None,
) -> Optional[str]:
    """Execute a slash command and return the response text.

    Returns the command response string, or None if the command is not found
    (caller should then treat the message as normal chat).
    """
    cmd = command_registry.get(cmd_name)
    if not cmd:
        return None  # Unknown command — fall through to normal LLM processing

    return cmd.handler(session_id, agent_id, external_user_id, channel_id, args)


# ==================== Built-in Command Handlers ====================


def _register_builtins():
    """Register all built-in slash commands."""

    # /clear — Clear chat history and agent llm log
    def clear_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from models.db import db
        import os

        db.clear_session(session_id, agent_id)

        # Reset agent state so next turn starts fresh in plan mode (no stale execute state).
        from backend.agent_state import AgentState
        fresh = AgentState()
        db.upsert_agent_state(fresh.serialize(), agent_id)

        now = __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        # Truncate agent's llm.log file
        log_path = os.path.join("logs", agent_id, "llm.log")
        if os.path.exists(log_path):
            with open(log_path, "w") as f:
                f.write(f"# LLM Log — Cleared on {now} UTC\n")

        # Truncate agent's sessrecap.log file
        recap_path = os.path.join("logs", agent_id, "sessrecap.log")
        if os.path.exists(recap_path):
            with open(recap_path, "w") as f:
                f.write(f"# Session Recap Log — Cleared on {now} UTC\n")

        # Emit session_clear event
        try:
            from backend.event_stream import event_stream
            event_stream.emit('session_clear', {'session_id': session_id, 'agent_id': agent_id})
        except Exception:
            pass

        return "History cleared."

    command_registry.register(
        "clear",
        clear_handler,
        "Clear chat history for this session",
    )

    # /help — Show available commands
    def help_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        commands = command_registry.list_commands()
        # Filter out /restart for non-super agents
        try:
            from models.db import db
            super_agent = db.get_super_agent()
            is_super = super_agent and super_agent.get('id') == agent_id
        except Exception:
            is_super = False
        lines = ["**Available commands:**"]
        for name, desc in commands:
            if name == "restart" and not is_super:
                continue
            lines.append(f"- `/{name}` — {desc}")
        return "\n".join(lines)

    command_registry.register(
        "help",
        help_handler,
        "Show available commands",
    )

    # /summary — Force regenerate session summary
    def summary_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from models.db import db
        from backend.agent_runtime import AgentRuntime

        rt = AgentRuntime()
        agent = db.get_agent(agent_id)
        if not agent:
            return "Error: Agent not found."

        # Trigger summarization for this session
        rt._maybe_summarize(agent, session_id)
        return "Session summary has been regenerated."

    command_registry.register(
        "summary",
        summary_handler,
        "Force regenerate session summary",
    )


    # /stop — Stop current agent processing loop
    def stop_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from backend.agent_runtime import agent_runtime  # global singleton (lazy import to avoid circular dep)
        agent_runtime.request_stop(session_id)
        return "Stop signal sent."

    command_registry.register(
        "stop",
        stop_handler,
        "Stop the agent's current processing loop",
    )

    # /cwd — Show current workspace directory
    def cwd_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from models.db import db

        agent = db.get_agent(agent_id)
        if not agent:
            return "Error: Agent not found."

        workspace = agent.get('workspace')
        if not workspace:
            return "No workspace directory configured."

        return f"Current workspace: {workspace}"

    command_registry.register(
        "cwd",
        cwd_handler,
        "Show current workspace directory",
    )

    # /cd — Change workspace directory (super agent only)
    def cd_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from models.db import db

        # super_agent = db.get_super_agent()
        # if not super_agent or super_agent.get('id') != agent_id:
        #     return "Permission denied: /cd is only available to the super agent."

        if not args or not args.strip():
            return "Usage: /cd [path] — change workspace directory"

        new_path = os.path.expanduser(args.strip())

        # Reject paths containing '..' to prevent directory traversal
        if '..' in new_path.split(os.sep):
            return f"Error: path contains '..' which is not allowed: {new_path}"

        # Resolve to absolute path and verify it exists
        new_path = os.path.abspath(new_path)
        if not os.path.isdir(new_path):
            return f"Error: directory does not exist: {new_path}"

        # Update agent workspace in DB
        db.update_agent(agent_id, {'workspace': new_path})

        # Destroy the old Docker container so the new workspace gets mounted on next tool use
        from backend.tools.runpy import _destroy_container
        _destroy_container(session_id)

        return f"Workspace changed to: {new_path}"

    command_registry.register(
        "cd",
        cd_handler,
        "Change workspace directory",
    )


    # /restart — Restart the service (super agent only)
    def restart_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from models.db import db

        super_agent = db.get_super_agent()
        if not super_agent or super_agent.get('id') != agent_id:
            return "Permission denied: /restart is only available to the super agent."

        # Persist caller info so the new process can notify them after boot
        import json as _json

        # Capture conversation context for contextual greeting after restart
        # Uses DB summary (compact) + last messages (raw) instead of sessrecap.log
        recent_context = ''
        try:
            # Get summary from chat_summaries table (compact LLM-generated summary)
            summary_data = db.get_summary(session_id, agent_id=agent_id)
            summary_text = summary_data.get('summary', '') if summary_data else ''

            # Get last ~5 message pairs (limit=12 to be safe for user+assistant alternation)
            last_messages = db.get_session_messages(session_id, limit=12, agent_id=agent_id)

            # Build context string
            parts = []
            if summary_text:
                parts.append('=== CONVERSATION SUMMARY ===')
                parts.append(summary_text)

            if last_messages:
                parts.append('=== LAST MESSAGES ===')
                for msg in last_messages:
                    role = msg.get('role', 'unknown')
                    # Skip tool result messages and assistant messages that are purely tool calls
                    if role == 'tool':
                        continue
                    if role == 'assistant' and msg.get('tool_calls') and not (msg.get('content') or '').strip():
                        continue
                    content = msg.get('content', '') or ''
                    if content:
                        parts.append(f'[{role}]: {content}')

            recent_context = '\n\n'.join(parts)
            # Truncate to ~3000 chars max
            if len(recent_context) > 3000:
                recent_context = recent_context[:3000] + '\n...(truncated)'

            _logger.info("Captured %d chars context from DB (summary + last_messages)", len(recent_context))
        except Exception as _e:
            _logger.error("Failed to read context from DB: %s", _e, exc_info=True)
            recent_context = ''

        db.set_setting('restart_greeting_needed', _json.dumps({
            'channel_id': channel_id,
            'external_user_id': external_user_id,
            'session_id': session_id,
            'context': recent_context,
        }))

        def _do_restart():
            import time
            time.sleep(1.5)  # Brief delay so response is sent first

            # Stop all channels cleanly so Telegram releases its long-poll
            # before the new process starts and re-opens them
            from backend.channels.registry import channel_manager
            channel_manager.stop_all()
            time.sleep(1.0)  # Give Telegram server-side time to release

            # Close all inherited file descriptors (including Flask's bound
            # socket) so the new process can bind the same port cleanly.
            # `resource` is POSIX-only; on Windows os.execv inherits handles
            # through the CRT and there's no RLIMIT_NOFILE to bound the loop.
            if sys.platform != 'win32':
                try:
                    import resource
                    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
                    if maxfd == resource.RLIM_INFINITY or maxfd > 65535:
                        maxfd = 4096
                    os.closerange(3, maxfd)
                except Exception:
                    pass

            os.execv(sys.executable, [sys.executable] + sys.argv)

        t = threading.Thread(target=_do_restart, daemon=True)
        t.start()
        return "Restarting..."

    command_registry.register(
        "restart",
        restart_handler,
        "Restart the service (super agent only)",
    )

    # /plan - Switch agent to plan mode
    def plan_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from backend.agent_state import AgentState
        from models.chat import agent_chat_manager

        # Create a fresh AgentState in plan mode
        ms = AgentState()

        # Persist state to dedicated agent_state table
        agent_chat_manager.get(agent_id).upsert_agent_state(ms.serialize())

        return "Switched to plan mode."

    command_registry.register(
        "plan",
        plan_handler,
        "Switch to plan mode",
    )

    def unfocus_handler(
        session_id: str,
        agent_id: str,
        external_user_id: str,
        channel_id: Optional[str],
        args: str,
    ) -> str:
        from backend.agent_state import AgentState
        from models.chat import agent_chat_manager

        content = agent_chat_manager.get(agent_id).get_agent_state()
        if not content:
            return "Tidak ada agent state aktif."
        ms = AgentState.deserialize(content)
        if not ms.focus:
            return "Focus mode sudah off."
        reason = ms.focus_reason or "unknown"
        ms.focus = False
        ms.focus_reason = None
        agent_chat_manager.get(agent_id).upsert_agent_state(ms.serialize())
        return (f"Focus mode cleared (was: {reason}). "
                f"Agent sekarang bisa menerima semua session.")

    command_registry.register(
        "unfocus",
        unfocus_handler,
        "Force-clear focus mode — use when agent is stuck in focus after a failed task",
    )


# Register builtins at import time
_register_builtins()
