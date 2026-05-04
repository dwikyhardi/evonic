"""
Kanban update task tool — update assignee and/or status at once.

This is the successor to kanban_update_status. It supports updating
both status and assignee in a single call.
"""

from datetime import datetime, timezone
from plugins.kanban.db import kanban_db


def _now():
    return datetime.now(timezone.utc).isoformat()


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', '')
    task_id = args.get('task_id', '').strip().lstrip('#')
    new_status = args.get('status')
    new_assignee = args.get('assignee')
    new_title = args.get('title')
    new_description = args.get('description')
    new_priority = args.get('priority')

    if not task_id:
        return {'status': 'error', 'message': 'task_id is required'}

    # At least one field must be provided
    if new_status is None and new_assignee is None and new_title is None and new_description is None and new_priority is None:
        return {
            'status': 'error',
            'message': 'At least one of "status", "assignee", "title", "description", or "priority" must be provided',
        }

    # Validate status if provided
    if new_status is not None and new_status not in ('in-progress', 'paused', 'done'):
        return {
            'status': 'error',
            'message': "status must be 'in-progress', 'paused', or 'done'",
        }

    # Validate priority if provided
    if new_priority is not None and new_priority not in ('low', 'medium', 'high'):
        return {
            'status': 'error',
            'message': "priority must be 'low', 'medium', or 'high'",
        }

    task = kanban_db.get(task_id)
    if not task:
        return {'status': 'error', 'message': f'Task {task_id} not found'}

    # Authorization: only the assignee (or a super agent)
    # may update the task's progress status. Other field updates
    # (title, description, priority) are unrestricted.
    if new_status is not None:
        if task.get('assignee') != agent_id and not agent.get('is_super'):
            return {
                'status': 'error',
                'message': 'Only the assigned agent or a super agent can update this task',
            }

    # Build update fields
    fields = {'updated_at': _now()}

    if new_status is not None:
        fields['status'] = new_status
        # Auto-set completed_at when status becomes 'done'
        if new_status == 'done' and not task.get('completed_at'):
            fields['completed_at'] = _now()
        # Auto-set started_at when status becomes 'in-progress'
        if new_status == 'in-progress' and not task.get('started_at'):
            fields['started_at'] = _now()
        # Track paused_at when pausing/resuming
        if new_status == 'paused':
            fields['paused_at'] = _now()
        elif new_status == 'in-progress' and task.get('paused_at'):
            fields['paused_at'] = None

    if new_assignee is not None:
        stripped = new_assignee.strip() or None
        # Regular agents cannot reassign tasks to super agents
        if stripped and not agent.get('is_super'):
            try:
                from models.db import db
                target = db.get_agent(stripped)
                if target and target.get('is_super'):
                    return {
                        'status': 'error',
                        'message': 'You cannot assign tasks to the super agent. Only the super agent can manage their own tasks.'
                    }
            except Exception:
                pass  # fail open if DB is not available
        fields['assignee'] = stripped

    if new_title is not None:
        fields['title'] = new_title

    if new_description is not None:
        fields['description'] = new_description

    if new_priority is not None:
        fields['priority'] = new_priority

    updated = kanban_db.update(task_id, fields)

    # Log status change if status was updated
    old_status = task.get('status')
    if new_status is not None and old_status != new_status:
        kanban_db.log_task_status_change(task_id, old_status, new_status)

    # Emit event
    try:
        from backend.event_stream import event_stream
        event_stream.emit('kanban_task_updated', {'task': updated})
    except Exception:
        pass

    return {'status': 'success', 'task': updated}
