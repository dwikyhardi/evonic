"""
AgentAPI Plugin — Event Handlers

Handles turn_complete for API usage metric logging.
"""

import logging

_logger = logging.getLogger(__name__)

PLUGIN_ID = 'agentapi'


def on_turn_complete(event_data: dict, sdk):
    """Log API usage metrics when an agent finishes a turn.

    This is a best-effort hook: we don't have direct access to the
    bearer token context here.  The primary quota/logging happens in
    the route handlers.  This handler is for additional metrics like
    turn duration and token counts that become available only after
    the agent finishes processing.

    The event_data dict typically contains:
      - agent_id, session_id, thinking_duration, tool_calls, response
    """
    agent_id = event_data.get('agent_id', '')
    session_id = event_data.get('session_id', '')

    # Only log for API-originated sessions
    if not session_id.startswith('api:'):
        return

    thinking_duration = event_data.get('thinking_duration')
    tool_count = len(event_data.get('tool_trace', []))

    _logger.debug(
        "AgentAPI turn_complete: agent=%s session=%s "
        "thinking_duration=%s tool_count=%d",
        agent_id, session_id, thinking_duration, tool_count,
    )
