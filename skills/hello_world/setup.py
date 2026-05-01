"""
Hello World skill install/uninstall script.

Called by the skills manager during skill lifecycle events.
- install(context): called when the skill is installed or re-installed
- uninstall(context): called when the skill is removed

context dict contains:
  - skill_dir: absolute path to the skill directory
  - app_dir: absolute path to the main application directory
  - skill_id: the skill's ID string
"""


def install(context: dict) -> dict:
    """Validate environment and initialize the skill."""
    return {'success': True, 'message': 'Hello World skill installed successfully.'}


def uninstall(context: dict) -> dict:
    """Clean up any runtime artifacts created by this skill."""
    return {'success': True, 'message': 'Hello World skill uninstalled successfully.'}
