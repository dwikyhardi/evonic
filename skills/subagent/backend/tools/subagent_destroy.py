"""subagent_destroy — destroy a sub-agent."""

import logging
from backend.subagent_manager import subagent_manager

_logger = logging.getLogger(__name__)


def execute(agent: dict, args: dict) -> dict:
    """Destroy a sub-agent by its ID."""
    sub_id = args.get('sub_agent_id', '').strip()
    if not sub_id:
        return {'error': 'sub_agent_id is required.'}

    parent_id = agent.get('id', '')

    # Security: only the parent can destroy its own sub-agents
    sub = subagent_manager.get(sub_id)
    if sub and sub.get('parent_id') != parent_id:
        return {
            'error': (
                f"You cannot destroy sub-agent '{sub_id}' — it belongs to "
                f"agent '{sub.get('parent_id')}', not you ('{parent_id}')."
            ),
        }

    destroyed = subagent_manager.destroy(sub_id)

    if destroyed:
        return {
            'destroyed': True,
            'sub_agent_id': sub_id,
            'message': f"Sub-agent '{sub_id}' destroyed.",
        }
    else:
        return {
            'destroyed': False,
            'sub_agent_id': sub_id,
            'message': f"Sub-agent '{sub_id}' not found (may have already expired).",
        }
