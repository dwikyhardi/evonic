"""
Auto Improver — event handlers.
"""

from . import analysis


def on_turn_complete(ev, sdk):
    """Handle the turn_complete event — auto-analyze if enabled."""
    try:
        config = sdk.config or {}
        if not config.get("AUTO_ANALYSIS_ENABLED", False):
            return

        session_id = ev.get("session_id")
        agent_id = ev.get("agent_id", "")

        target_agent = config.get("TARGET_AGENT_ID", "")
        if target_agent and agent_id != target_agent:
            return

        min_turns = int(config.get("MIN_TURN_THRESHOLD", 3))
        depth = config.get("ANALYSIS_DEPTH", "medium")

        messages = sdk.get_session_messages(session_id, agent_id, limit=100)
        if not messages:
            sdk.log(f"No messages found for session {session_id}", level="warning")
            return

        if len(messages) < min_turns:
            sdk.log(f"Session {session_id} has {len(messages)} messages, below threshold of {min_turns}. Skipping.", level="debug")
            return

        sdk.log(f"Analyzing session {session_id} for agent {agent_id} ({len(messages)} messages)...")
        result = analysis.analyze_session(session_id, agent_id, messages, depth=depth)
        result["stored_messages"] = messages
        analysis.save_analysis_result(result)

        sdk.log(f"Analysis complete: score={result['score']}, issues={len(result['issues'])}")

        critical_issues = [i for i in result["issues"] if i.get("severity") in ["critical", "high"]]
        if critical_issues:
            sdk.log(f"⚠️ {len(critical_issues)} high/critical issue(s) found in session {session_id}", level="warning")
            for issue in critical_issues:
                sdk.log(f"  - [{issue['severity'].upper()}] {issue['message']}", level="warning")

    except Exception as e:
        sdk.log(f"Error in on_turn_complete: {str(e)}", level="error")
