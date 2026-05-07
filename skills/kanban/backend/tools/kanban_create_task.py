"""
Kanban create task tool — create a new task on the Kanban board.

Permission is controlled by setting 'kanban:create_task_super_only':
- '0' (disabled): all agents can create tasks
- '1' (default/enabled): only super agent can create tasks (default)
"""

from datetime import datetime, timezone
from plugins.kanban.db import kanban_db


def _now():
    return datetime.now(timezone.utc).isoformat()


def execute(agent: dict, args: dict) -> dict:
    # Check create_task_super_only setting via skill config
    try:
        from backend.skills_manager import skills_manager
        config = skills_manager.get_skill_config('kanban')
        super_only = bool(config.get('create_task_super_only', True))
    except Exception:
        super_only = True  # fail closed

    if super_only and not agent.get('is_super'):
        return {
            'status': 'error',
            'message': 'You are not authorized to create tasks. Only the super agent can create tasks.'
        }

    title = (args.get('title') or '').strip()
    if not title:
        return {'status': 'error', 'message': 'title is required'}

    description = (args.get('description') or '').strip()
    priority = (args.get('priority') or 'low').strip().lower()
    if priority not in ('low', 'medium', 'high'):
        return {'status': 'error', 'message': "priority must be 'low', 'medium', or 'high'"}

    assignee = (args.get('assignee') or '').strip() or None

    # Regular agents cannot assign tasks to super agents
    if assignee and not agent.get('is_super'):
        try:
            from models.db import db
            target = db.get_agent(assignee)
            if target and target.get('is_super'):
                return {
                    'status': 'error',
                    'message': 'You cannot assign tasks to the super agent. Only the super agent can manage their own tasks.'
                }
        except Exception:
            pass  # fail open if DB is not available

    now = _now()
    task_data = {
        'title': title,
        'description': description,
        'status': 'todo',
        'priority': priority,
        'assignee': assignee,
        'created_at': now,
        'updated_at': now,
    }

    created = kanban_db.create(task_data)
    kanban_db.log_task_created(created['id'])

    return {
        'status': 'success',
        'task': created,
    }
