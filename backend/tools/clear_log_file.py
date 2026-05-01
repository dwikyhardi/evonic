import os

def execute(agent: dict, args: dict) -> dict:
    """
    Truncates the agent-specific llm.log and sessrecap.log files and adds a reset marker.
    """
    agent_id = agent.get('id')
    if not agent_id:
        return {"error": "Agent ID not found in agent context."}

    # Construct paths to logs/{agent_id}/llm.log and sessrecap.log
    log_path = os.path.join("logs", agent_id, "llm.log")
    recap_path = os.path.join("logs", agent_id, "sessrecap.log")

    # Ensure directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    marker = "---log-reset---\n"

    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(marker)
    except Exception as e:
        return {"error": f"Error clearing llm.log: {str(e)}"}

    try:
        with open(recap_path, 'w', encoding='utf-8') as f:
            f.write(marker)
    except Exception as e:
        return {"error": f"Error clearing sessrecap.log: {str(e)}"}

    return {"result": f"Successfully cleared log files for agent {agent_id}"}