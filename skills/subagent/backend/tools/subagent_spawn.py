"""subagent_spawn — spawn a new sub-agent."""

import logging
from backend.subagent_manager import subagent_manager
from backend.agent_runtime.notifier import notify_agent

_logger = logging.getLogger(__name__)


def execute(agent: dict, args: dict) -> dict:
    """Spawn a new sub-agent and send it an initial task message."""
    from models.db import db

    parent_id = agent.get('id', '')
    if not parent_id:
        return {'error': 'Cannot determine parent agent ID from context.'}

    task = args.get('task', '').strip()
    if not task:
        return {'error': 'A task description is required. Use subagent_spawn({task: "..."}).'}

    parent_agent = db.get_agent(parent_id)
    if not parent_agent:
        return {'error': f'Parent agent "{parent_id}" not found in DB.'}

    try:
        sub_id = subagent_manager.spawn(parent_agent)
    except ValueError as e:
        return {'error': str(e)}

    parent_name = parent_agent.get('name', parent_id)
    result = notify_agent(
        agent_id=sub_id,
        tag=f"AGENT/{parent_name}",
        message=task,
        external_user_id=f"__agent__{parent_id}",
        channel_id=None,
        dedup=False,
        trigger_llm=True,
        metadata={
            'agent_message': True,
            'from_agent_id': parent_id,
            'from_agent_name': parent_name,
            'agent_message_depth': 1,
            'subagent_spawn': True,
        },
    )

    _logger.info(
        "Sub-agent %s spawned by %s with task: %s (notify_result=%s)",
        sub_id, parent_id, task[:100], result,
    )

    return {
        'sub_agent_id': sub_id,
        'task': task,
        'message': (
            f"Sub-agent spawned with ID '{sub_id}'. "
            f"It will process the task and report back via agent messaging. "
            f"Use subagent_list() to check on it."
        ),
    }
