# Scheduler Skill

You have access to a global scheduler that lets you create timed jobs: one-shot reminders, recurring tasks, and cron-based triggers.

## Quick Reference

### One-shot reminder (fire once at a specific time)
```json
{
  "name": "Remind about meeting",
  "trigger_type": "date",
  "trigger_config": {"run_date": "2026-04-21T14:00:00"},
  "action_type": "agent_message",
  "action_config": {"message": "Reminder: team meeting in 15 minutes!"}
}
```

### Recurring interval (every N minutes/hours)
```json
{
  "name": "Check deploy status",
  "trigger_type": "interval",
  "trigger_config": {"minutes": 30},
  "action_type": "agent_message",
  "action_config": {"message": "Please check the deployment status."}
}
```

### Cron schedule (e.g. weekdays at 9 AM)
```json
{
  "name": "Daily standup reminder",
  "trigger_type": "cron",
  "trigger_config": {"day_of_week": "mon-fri", "hour": 9, "minute": 0},
  "action_type": "agent_message",
  "action_config": {"message": "Good morning! Time for the daily standup."}
}
```

## Notes
- When using `agent_message` action, if you omit `agent_id` in `action_config`, the message is sent to you (the calling agent).
- Use `list_schedules` to see your active schedules and their IDs.
- Use `cancel_schedule` with the schedule ID to stop a recurring job.
- All times are in server local time unless otherwise specified.
- `date` triggers automatically set `max_runs=1`.
