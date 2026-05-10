"""
Kanban get comments tool — retrieve paginated comments for a task.
"""

from plugins.kanban.db import kanban_db


def execute(agent: dict, args: dict) -> dict:
    task_id = args.get('task_id', '').strip()
    if not task_id:
        return {
            'status': 'error',
            'message': 'task_id is required',
        }

    limit = args.get('limit', 10)
    offset = args.get('offset', 0)

    # Validate limit
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(limit, 100))

    # Validate offset
    try:
        offset = int(offset)
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)

    result = kanban_db.get_comments_paginated(task_id, limit, offset)

    return {
        'status': 'success',
        'comments': result['comments'],
        'total': result['total'],
        'limit': limit,
        'offset': offset,
    }
