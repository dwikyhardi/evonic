"""List scheduled jobs for the calling agent."""

from backend.scheduler import scheduler


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', '')
    include_disabled = bool(args.get('include_disabled', False))
    show_all = bool(args.get('all', False))

    is_super = agent.get('is_super', False)

    if show_all and not is_super:
        return {'status': 'error', 'error': 'Permission denied. Only super admin can list all schedules.'}

    if show_all:
        schedules = scheduler.list_schedules(enabled_only=not include_disabled)
    else:
        schedules = scheduler.list_schedules(
            owner_type='agent',
            owner_id=agent_id,
            enabled_only=not include_disabled,
        )

    items = []
    for s in schedules:
        items.append({
            'schedule_id': s['id'],
            'name': s['name'],
            'owner_type': s['owner_type'],
            'owner_id': s['owner_id'],
            'trigger_type': s['trigger_type'],
            'trigger_config': s['trigger_config'],
            'action_type': s['action_type'],
            'enabled': bool(s['enabled']),
            'next_run_at': s.get('next_run_at'),
            'last_run_at': s.get('last_run_at'),
            'run_count': s['run_count'],
            'max_runs': s.get('max_runs'),
        })

    return {
        'status': 'success',
        'count': len(items),
        'schedules': items,
    }
