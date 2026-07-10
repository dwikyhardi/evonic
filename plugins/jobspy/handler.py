"""Event handler for JobSpy-owned scheduler events."""

from plugins.jobspy.db import jobspy_db
from plugins.jobspy.service import JobSpyService


def on_schedule_fired(event, sdk):
    if event.get('owner_type') != 'plugin' or event.get('owner_id') != 'jobspy':
        return
    profile = jobspy_db.get_profile_by_schedule(event.get('schedule_id'))
    if not profile or not profile.get('enabled'):
        return
    timeout = sdk.config.get('SUBPROCESS_TIMEOUT_SECONDS', 180)
    service = JobSpyService(jobspy_db, timeout_seconds=timeout)
    result = service.run_profile(profile['id'], sdk=sdk)
    if result['run']['status'] not in ('success', 'partial'):
        sdk.log(
            f"JobSpy run {result['run']['id']} ended with {result['run']['status']}",
            'warn',
        )


def dashboard_jobspy_card(sdk):
    try:
        summary = jobspy_db.summary(high_score=75)
        last_run = summary.get('last_run') or {}
        last_status = last_run.get('status') or 'never run'
        return {
            'id': 'jobspy_matches',
            'title': 'JobSpy Matches',
            'link': '/jobspy',
            'feature_card': {
                'count': str(summary.get('new_high_matches', 0)),
                'detail': (
                    f"{summary.get('jobs', 0)} jobs · last run {last_status}"
                ),
                'border_color': 'emerald',
                'bg_color': 'emerald',
                'icon_color': 'emerald',
            },
        }
    except Exception:
        return None