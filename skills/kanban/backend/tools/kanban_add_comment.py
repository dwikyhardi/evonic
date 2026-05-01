"""
Kanban add comment tool — log progress notes on a kanban task.
"""

from plugins.kanban.db import kanban_db


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', '')
    task_id = args.get('task_id', '').strip().lstrip('#')
    content = args.get('content', '').strip()

    if not task_id:
        return {'status': 'error', 'message': 'task_id is required'}
    if not content:
        return {'status': 'error', 'message': 'content is required'}

    task = kanban_db.get(task_id)
    if not task:
        return {'status': 'error', 'message': f'Task {task_id} not found'}

    if task.get('assignee') != agent_id and task.get('picked_by') != agent_id:
        return {'status': 'error', 'message': 'You are not authorized to comment on this task'}

    comment = kanban_db.add_comment(task_id, content, author=agent_id)
    if not comment:
        return {'status': 'error', 'message': 'Failed to add comment'}

    return {'status': 'success', 'comment': comment}
