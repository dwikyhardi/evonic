"""
Builtin tool: unload_skill

Remove a previously lazy-loaded skill's tools from the current LLM context.
After calling this, the skill's tool functions will no longer be available
in this conversation turn.

Usage: unload_skill({id: "plugin_creator"})
"""

import os
import json
from backend.skills_manager import skills_manager


def execute(agent: dict, args: dict) -> dict:
    """
    Signal the runtime to remove a lazy-loaded skill's tools from context.

    Only works for skills with lazy_tools=true — eager skills cannot be unloaded
    because their tools are loaded at startup.

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

    # Verify this is a lazy skill — eager skills can't be unloaded
    skill = skills_manager.get_skill(skill_id)
    if skill:
        skill_dir = skill.get('_dir', os.path.join(
            os.path.dirname(__file__), '..', '..', 'skills', skill_id
        ))
        manifest_path = os.path.join(os.path.normpath(skill_dir), 'skill.json')
        manifest = {}
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, encoding='utf-8') as f:
                    manifest = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        if not manifest.get('lazy_tools', False):
            return {
                "status": "error",
                "id": skill_id,
                "message": (
                    f"Skill '{skill_id}' is eagerly loaded — its tools are always available "
                    f"and cannot be unloaded. unload_skill only works with lazy-loaded skills."
                )
            }

    return {
        "status": "success",
        "id": skill_id,
        "remove_tools": True,
        "message": f"Skill '{skill_id}' has been unloaded. Its tools are no longer available in this context."
    }
