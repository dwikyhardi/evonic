"""Cancel a scheduled job."""

from backend.scheduler import scheduler


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', '')
    is_super = agent.get('is_super', False)
    schedule_id = args.get('schedule_id', '').strip()

    if not schedule_id:
        return {'status': 'error', 'error': 'schedule_id is required'}

    # Super admin can cancel any schedule; regular agents only their own
    owner_id = None if is_super else agent_id
    success = scheduler.cancel_schedule(schedule_id, owner_id=owner_id)
    if success:
        return {'status': 'success', 'message': f'Schedule {schedule_id} cancelled.'}
    else:
        return {'status': 'error', 'error': 'Schedule not found or not owned by you.'}
