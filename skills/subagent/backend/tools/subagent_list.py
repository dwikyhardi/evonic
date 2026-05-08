"""subagent_list — list live sub-agents for the calling agent."""

import time
import logging
from datetime import datetime
from backend.subagent_manager import subagent_manager

_logger = logging.getLogger(__name__)


def execute(agent: dict, args: dict) -> dict:
    """List all live sub-agents for the calling agent."""
    parent_id = agent.get('id', '')
    if not parent_id:
        return {'error': 'Cannot determine agent ID from context.'}

    subs = subagent_manager.list_subagents(parent_id)

    for s in subs:
        s['created_at_iso'] = datetime.fromtimestamp(s['created_at']).isoformat()
        s['last_active_at_iso'] = datetime.fromtimestamp(s['last_active_at']).isoformat()
        s['idle_seconds'] = round(time.time() - s['last_active_at'], 1)

    return {
        'subagents': subs,
        'count': len(subs),
    }
