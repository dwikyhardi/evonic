"""Backend implementation for the create_booking tool."""
import json

def execute(agent, args: dict) -> dict:
    # agent: dict with agent_id, agent_name, user_id, channel_id, session_id
    # args: dict of arguments passed by the LLM
    return "Booking created: %s" % json.dumps(args)
