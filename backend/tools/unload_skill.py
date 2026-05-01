"""
Builtin tool: unload_skill

Remove a previously lazy-loaded skill's tools from the current LLM context.
After calling this, the skill's tool functions will no longer be available
in this conversation turn.

Usage: unload_skill({id: "plugin_creator"})
"""


def execute(agent: dict, args: dict) -> dict:
    """
    Signal the runtime to remove a lazy-loaded skill's tools from context.

    Args:
        agent: Agent context dict.
        args: Must contain 'id' — the ID of the skill to unload.

    Returns:
        dict with remove_tools=True so the runtime can act on it.
    """
    skill_id = args.get("id", "").strip()

    if not skill_id:
        return {
            "status": "error",
            "message": "id is required."
        }

    return {
        "status": "success",
        "id": skill_id,
        "remove_tools": True,
        "message": f"Skill '{skill_id}' has been unloaded. Its tools are no longer available in this context."
    }
