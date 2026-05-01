"""
Kanban get task tool — retrieve a single task by ID.
"""

from plugins.kanban.db import kanban_db


def execute(agent: dict, args: dict) -> dict:
    task_id = args.get('task_id', '').strip()
    if not task_id:
        return {
            'status': 'error',
            'message': 'task_id is required',
        }

    task = kanban_db.get(task_id)
    if not task:
        return {
            'status': 'not_found',
            'message': f'Task with id "{task_id}" not found',
        }

    last_comment = kanban_db.get_last_comment(str(task_id))
    return {
        'status': 'success',
        'task': task,
        'last_comment': last_comment,
    }
