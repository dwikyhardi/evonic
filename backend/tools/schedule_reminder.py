"""
schedule_reminder tool — allows an agent to schedule a delayed push notification
to the user on their current channel.

Example agent usage:
    schedule_reminder(delay_minutes=10, message="Waktunya mandi!")
"""

from datetime import datetime, timezone, timedelta
from backend.scheduler import scheduler


def execute(agent: dict, args: dict) -> dict:
    delay_minutes = args.get("delay_minutes", 0)
    message = args.get("message", "")

    # --- Validation -----------------------------------------------------------
    if not isinstance(delay_minutes, (int, float)) or delay_minutes <= 0:
        return {
            "error": (
                "delay_minutes must be a positive number. "
                "Example: schedule_reminder(delay_minutes=10, message='...')"
            ),
        }
    if not message or not isinstance(message, str) or not message.strip():
        return {
            "error": "message must be a non-empty string.",
        }

    # --- Gather routing info from agent context -------------------------------
    channel_id = agent.get("channel_id")
    external_user_id = agent.get("user_id")
    agent_id = agent.get("agent_id", "unknown")

    if not channel_id:
        return {
            "error": (
                "Cannot schedule a reminder — no channel_id available in the "
                "current context. This tool only works when the user is chatting "
                "via an external channel (Telegram, WhatsApp, etc.)."
            ),
        }
    if not external_user_id:
        return {
            "error": (
                "Cannot schedule a reminder — no user_id (external_user_id) "
                "available in the current context."
            ),
        }

    # --- Calculate the fire time ----------------------------------------------
    run_date = (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).isoformat()

    # --- Create the schedule entry --------------------------------------------
    try:
        schedule = scheduler.create_schedule(
            name=f"Reminder: {message[:60]}{'...' if len(message) > 60 else ''}",
            owner_type="agent",
            owner_id=agent_id,
            trigger_type="date",
            trigger_config={"run_date": run_date},
            action_type="user_notification",
            action_config={
                "channel_id": channel_id,
                "external_user_id": external_user_id,
                "message": message.strip(),
            },
            metadata={
                "created_by_agent": agent_id,
                "channel_id": channel_id,
                "external_user_id": external_user_id,
                "original_message": message.strip(),
            },
        )
    except Exception as e:
        return {
            "error": f"Failed to create schedule: {e}",
        }

    return {
        "success": True,
        "schedule_id": schedule["id"],
        "message": message.strip(),
        "delay_minutes": delay_minutes,
        "will_fire_at": run_date,
        "channel_id": channel_id,
        "detail": (
            f"Reminder scheduled! I'll notify you in {delay_minutes} "
            f"minute(s): \"{message.strip()}\""
        ),
    }


# ---------------------------------------------------------------------------
# Self-contained tests (auto-discovered by unit_tests/test_tool_backends.py)
# ---------------------------------------------------------------------------

def test_execute():
    """Run all tests for the schedule_reminder tool backend."""
    from unittest.mock import MagicMock, patch

    # --- Test: successful scheduling ---------------------------------------
    mock_sched = MagicMock()
    mock_sched.create_schedule.return_value = {
        "id": "test-sched-001",
        "name": "Reminder: Hello!",
    }
    with patch("backend.tools.schedule_reminder.scheduler", mock_sched):
        agent = {
            "agent_id": "agent-1",
            "channel_id": "ch-tg",
            "user_id": "user-42",
        }
        result = execute(agent, {"delay_minutes": 5, "message": "Hello!"})
        assert result["success"] is True
        assert result["schedule_id"] == "test-sched-001"
        assert result["delay_minutes"] == 5
        assert result["channel_id"] == "ch-tg"
        assert mock_sched.create_schedule.called
        call_kwargs = mock_sched.create_schedule.call_args[1]
        assert call_kwargs["action_type"] == "user_notification"
        assert call_kwargs["trigger_type"] == "date"
        assert call_kwargs["action_config"]["channel_id"] == "ch-tg"
        assert call_kwargs["action_config"]["external_user_id"] == "user-42"
        assert call_kwargs["action_config"]["message"] == "Hello!"

    # --- Test: invalid delay_minutes --------------------------------------
    result = execute(
        {"channel_id": "ch-tg", "user_id": "u1"},
        {"delay_minutes": 0, "message": "Hi"},
    )
    assert "error" in result
    assert "positive number" in result["error"]

    result = execute(
        {"channel_id": "ch-tg", "user_id": "u1"},
        {"delay_minutes": -5, "message": "Hi"},
    )
    assert "error" in result

    # --- Test: empty message ----------------------------------------------
    result = execute(
        {"channel_id": "ch-tg", "user_id": "u1"},
        {"delay_minutes": 5, "message": ""},
    )
    assert "error" in result
    assert "non-empty" in result["error"]

    result = execute(
        {"channel_id": "ch-tg", "user_id": "u1"},
        {"delay_minutes": 5, "message": "   "},
    )
    assert "error" in result

    # --- Test: missing channel_id -----------------------------------------
    result = execute(
        {"user_id": "u1"},
        {"delay_minutes": 5, "message": "Hi"},
    )
    assert "error" in result
    assert "channel_id" in result["error"]

    # --- Test: missing user_id --------------------------------------------
    result = execute(
        {"channel_id": "ch-tg"},
        {"delay_minutes": 5, "message": "Hi"},
    )
    assert "error" in result
    assert "user_id" in result["error"]
