"""
Kanban search tasks tool — list tasks on the board.
"""

from plugins.kanban.db import kanban_db


def _is_task_id(value: str) -> bool:
    """Return True if value looks like a bare task ID (all digits)."""
    return value.isdigit()


def execute(agent: dict, args: dict) -> dict:
    status_filter = args.get('status', '').strip() or None
    query = args.get('query', '').strip() or None
    assignee_filter = args.get('assignee', '').strip() or None
    limit = args.get('limit', 20)
    if not isinstance(limit, int) or limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    # ID-based lookup: if query looks like a task ID, try direct fetch first
    if query and _is_task_id(query):
        task = kanban_db.get(query)
        if task:
            # Respect status/assignee filters when returning ID-matched task
            if status_filter and task.get('status') != status_filter:
                return {'status': 'success', 'count': 0, 'tasks': [], 'query_id': query}
            if assignee_filter and task.get('assignee') != assignee_filter:
                return {'status': 'success', 'count': 0, 'tasks': [], 'query_id': query}
            return {'status': 'success', 'count': 1, 'tasks': [task], 'query_id': query}

    tasks = kanban_db.get_all()
    relevant = list(tasks)

    # Filter by assignee (optional)
    if assignee_filter:
        relevant = [t for t in relevant if t.get('assignee') == assignee_filter]

    # Filter by status
    if status_filter:
        relevant = [t for t in relevant if t.get('status') == status_filter]

    # Filter by query (case-insensitive search on title and description)
    if query:
        q = query.lower()
        relevant = [
            t for t in relevant
            if q in (t.get('title', '') or '').lower()
            or q in (t.get('description', '') or '').lower()
        ]

    # Sort newest first by updated_at, fallback to created_at
    relevant.sort(
        key=lambda t: (t.get('updated_at') or t.get('created_at') or ''),
        reverse=True
    )

    # Apply limit
    relevant = relevant[:limit]

    return {
        'status': 'success',
        'count': len(relevant),
        'tasks': relevant,
    }
