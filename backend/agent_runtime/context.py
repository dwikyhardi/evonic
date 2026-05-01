"""
context.py — builds LLM input: system prompt, tool list, message formatting.

Pure data preparation — no LLM calls, no threading.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from models.db import db
from backend.tools import tool_registry
from backend.skills_manager import SkillsManager
from config import AGENT_MAX_TOOL_RESULT_CHARS as MAX_TOOL_RESULT_CHARS

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AGENTS_DIR = os.path.join(_BASE_DIR, 'agents')

# Per-agent cache for the static portion of build_system_prompt.
# Entries are invalidated when tracked file/dir mtimes change.
# Structure: { agent_id: { "static_prompt": str, "sp_mtime": float, "kb_mtime": float,
#                           "skills_mtimes": dict, "tools_hash": str, "ctx_mtime": float } }
_system_prompt_cache: Dict[str, Dict[str, Any]] = {}


def _system_prompt_path(agent_id: str) -> str:
    return os.path.join(_AGENTS_DIR, agent_id, 'SYSTEM.md')


def _get_mtime(path: str) -> float:
    """Return mtime of a file or dir, or 0 if it doesn't exist."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _build_static_prompt(agent: Dict[str, Any]) -> str:
    """Build the static portion of the system prompt (no datetime, no onboarding).

    This is cached per-agent and invalidated only when underlying files/dirs change.
    """
    parts = []
    aid = agent['id']

    # Optionally inject agent ID at the top
    if agent.get('inject_agent_id'):
        parts.append(f"Your agent ID is: {aid}")

    # Read system prompt from file; fall back to DB value for backward compat
    sp_path = _system_prompt_path(aid)
    if os.path.isfile(sp_path):
        try:
            with open(sp_path, 'r', encoding='utf-8') as f:
                sp = f.read().strip()
            if sp:
                parts.append(sp)
        except Exception:
            pass
    elif agent.get('system_prompt'):
        parts.append(agent['system_prompt'])

    # Language preference injection
    _agent_lang = db.get_setting('agent_language')
    if _agent_lang:
        _lang_instructions = {
            'english': 'Always respond in English.',
            'indonesian': 'Always respond in Bahasa Indonesia.',
            'adaptive': 'Respond in the same language the user uses. If the user mixes languages, you may mix too.',
        }
        _lang_text = _lang_instructions.get(_agent_lang, '')
        if _lang_text:
            parts.append(f"\n## Language\n{_lang_text}")

    # Inject system_prompt from assigned tool definitions
    assigned_ids = set(db.get_agent_tools(aid))
    if assigned_ids:
        seen_fn_names = set()
        for tool_def in tool_registry.get_all_tool_defs():
            tool_id = tool_def.get('id', '')
            fn_name = tool_def.get('function', {}).get('name', '')
            if tool_id in assigned_ids or fn_name in assigned_ids:
                if fn_name in seen_fn_names:
                    continue
                seen_fn_names.add(fn_name)
                tool_prompt = tool_def.get('system_prompt', '').strip()
                if tool_prompt:
                    parts.append(tool_prompt)

    # List available KB files so the agent knows what it can read
    kb_dir = os.path.join(_AGENTS_DIR, aid, 'kb')
    if os.path.isdir(kb_dir):
        files = [f for f in sorted(os.listdir(kb_dir))
                 if os.path.isfile(os.path.join(kb_dir, f))]
        if files:
            parts.append("\n## Available Knowledge Files")
            parts.append("You can read these files using the `read` tool:")
            for f in files:
                size = os.path.getsize(os.path.join(kb_dir, f))
                parts.append(f"- {f} ({size / 1024:.1f} KB)")
            parts.append("")
            parts.append("### KB Usage")
            parts.append("- **Save**: Use `write_file` with path `agents/<your_id>/kb/filename` to store a new KB file.")
            parts.append("- **Read**: Use the `read` tool with the bare filename (no path) to read a KB file.")
            parts.append("- **KB vs Remember**: Use `read` for reference documents, guides, and long-form content. Use `remember` for short, searchable facts you want to recall across conversations.")
            parts.append("- **Best practices**: Store structured reference material in KB (specs, API docs, conventions). Keep each file focused on one topic. Update KB files when information changes.")

    # List available skills with SYSTEM.md so the agent knows what it can load
    skills_mgr = SkillsManager()
    _allowed_skills = None if agent.get('is_super') else set(db.get_agent_skills(aid))
    skills_with_system_md = []
    for skill in skills_mgr.list_skills():
        if not skills_mgr.is_skill_enabled(skill.get('id', '')):
            continue
        # Hide super_only skills from regular agents
        if skill.get('super_only', False) and not agent.get('is_super'):
            continue
        # Hide skills not in this agent's allowlist (regular agents only)
        if _allowed_skills is not None and skill['id'] not in _allowed_skills:
            continue
        skill_dir = skill.get('_dir', os.path.join(_BASE_DIR, 'skills', skill['id']))
        system_md_path = os.path.join(skill_dir, 'SYSTEM.md')
        if os.path.isfile(system_md_path):
            desc = skill.get('description', '')
            skills_with_system_md.append((skill['id'], desc))

    if skills_with_system_md:
        parts.append("\n## Skills")
        parts.append("You have these skills that can be loaded using `use_skill` tool:")
        for skill_id, desc in skills_with_system_md:
            parts.append(f"- `{skill_id}` - {desc}")

    return "\n".join(parts) if parts else "You are a helpful assistant."


def _cache_key_valid(agent: Dict[str, Any], cache_entry: Dict[str, Any]) -> bool:
    """Check if the cached static prompt is still valid by comparing mtimes."""
    aid = agent['id']

    # Check SYSTEM.md mtime
    sp_path = _system_prompt_path(aid)
    if _get_mtime(sp_path) != cache_entry['sp_mtime']:
        return False

    # Check KB dir mtime
    kb_dir = os.path.join(_AGENTS_DIR, aid, 'kb')
    if _get_mtime(kb_dir) != cache_entry['kb_mtime']:
        return False

    # Check skills mtimes
    cached_skills_mtimes = cache_entry.get('skills_mtimes', {})
    skills_mgr = SkillsManager()
    for skill in skills_mgr.list_skills():
        sid = skill.get('id', '')
        skill_dir = skill.get('_dir', os.path.join(_BASE_DIR, 'skills', sid))
        system_md_path = os.path.join(skill_dir, 'SYSTEM.md')
        current_mtime = _get_mtime(system_md_path)
        if current_mtime != cached_skills_mtimes.get(sid, 0.0):
            return False

    # Check tools hash (assigned tool IDs)
    assigned_ids = frozenset(db.get_agent_tools(aid))
    if str(sorted(assigned_ids)) != cache_entry['tools_hash']:
        return False

    # Check context.py mtime (for injected sections like slash commands)
    if _get_mtime(__file__) != cache_entry.get('ctx_mtime', 0.0):
        return False

    return True


def build_system_prompt(agent: Dict[str, Any]) -> str:
    """Build the system prompt including tool injections and KB file listing.

    The static portion (SYSTEM.md, KB files, skills) is cached per-agent and
    invalidated only when underlying files/dirs change (mtime check).
    Dynamic portions (onboarding, datetime) are always re-evaluated.
    """
    aid = agent['id']

    # Check cache
    cache_entry = _system_prompt_cache.get(aid)
    if cache_entry is not None and _cache_key_valid(agent, cache_entry):
        static_prompt = cache_entry['static_prompt']
    else:
        # Cache miss or invalid — rebuild static portion
        static_prompt = _build_static_prompt(agent)

        # Build mtime snapshot for cache validation
        sp_path = _system_prompt_path(aid)
        kb_dir = os.path.join(_AGENTS_DIR, aid, 'kb')
        skills_mtimes = {}
        skills_mgr = SkillsManager()
        for skill in skills_mgr.list_skills():
            sid = skill.get('id', '')
            skill_dir = skill.get('_dir', os.path.join(_BASE_DIR, 'skills', sid))
            system_md_path = os.path.join(skill_dir, 'SYSTEM.md')
            skills_mtimes[sid] = _get_mtime(system_md_path)

        assigned_ids = frozenset(db.get_agent_tools(aid))

        _system_prompt_cache[aid] = {
            'static_prompt': static_prompt,
            'sp_mtime': _get_mtime(sp_path),
            'kb_mtime': _get_mtime(kb_dir),
            'skills_mtimes': skills_mtimes,
            'tools_hash': str(sorted(assigned_ids)),
            'ctx_mtime': _get_mtime(__file__),
        }

    prompt = static_prompt

    # Onboarding injection for super agent (one-time, until owner name is known).
    # Once set_owner_name is called, defaults/super_agent_system_prompt.md is copied
    # to SYSTEM.md and owner_name is stored — the injection below is then replaced
    # by a simple personalization line.
    if agent.get('is_super'):
        _owner_name = db.get_setting('owner_name')
        if not _owner_name:
            prompt += (
                "\n\n## IMPORTANT: First-Time Onboarding\n"
                "This is your first conversation. You MUST:\n"
                f"1. Introduce yourself — your name is **{agent.get('name', 'Agent')}**\n"
                "2. Ask for the platform owner's name\n"
                "3. Once you learn their name, call the `set_owner_name` tool with their name\n"
                "4. Then greet them warmly and offer help\n\n"
                "Do not do anything else before you know the owner's name."
            )
        else:
            prompt += f"\n\nYour owner's name is: **{_owner_name}**"

    if agent.get('inject_datetime'):
        gmt7 = timezone(timedelta(hours=7))
        now = datetime.now(gmt7)
        has_template_vars = any(v in prompt for v in ('{{time}}', '{{date}}', '{{day}}'))
        # Replace inline template vars (backward compat for existing SYSTEM.md files)
        prompt = prompt.replace('{{time}}', now.strftime('%H:%M:%S'))
        prompt = prompt.replace('{{date}}', now.strftime('%Y-%m-%d'))
        prompt = prompt.replace('{{day}}', now.strftime('%A'))
        # Auto-append datetime block if no inline template vars were present
        if not has_template_vars:
            prompt += (f"\n\nCurrent date/time: {now.strftime('%A')}, "
                       f"{now.strftime('%Y-%m-%d')}, {now.strftime('%H:%M:%S')} (WIB/UTC+7)")

    # Always append the empty-response recovery instruction
    prompt += (
        "\n\n## Response Recovery Rule\n"
        "If you are asked \"[SYSTEM] Please continue and give your response.\", it means "
        "your previous turn produced no visible reply. Continue your work or provide your "
        "response now. If you genuinely have nothing to say (e.g. the message was "
        "internal/system noise that requires no reply), respond with exactly: `[No response needed]`"
    )

    # Dynamically inject slash commands based on agent permissions
    is_super = bool(agent.get('is_super'))
    slash_commands = [
        ("/clear", "Clear chat history for this session"),
        ("/help", "Show available commands"),
        ("/summary", "Force regenerate session summary"),
        ("/stop", "Stop the agent's current processing loop"),
        ("/cwd", "Show current workspace directory"),
        ("/cd", "Change workspace directory"),
    ]
    if is_super:
        slash_commands.append(("/restart", "Restart the service (super agent only)"))
    slash_commands.append(("/plan", "Switch to plan mode"))
    slash_commands.append(("/unfocus", "Force-clear focus mode — use when agent is stuck in focus after a failed task"))
    # /autopilot is not yet implemented, omit from listing

    if slash_commands:
        prompt += "\n\n## Slash Commands\n\n**Available commands:**\n"
        for name, desc in slash_commands:
            prompt += f"- `{name}` — {desc}\n"

    return prompt


def build_tools(agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the OpenAI function tool list for this agent."""
    tools = []

    # Always include built-in tools (read, etc.)
    agent_context = {
        'id': agent['id'],
        'is_super': bool(agent.get('is_super')),
    }
    tools.extend(tool_registry.get_builtin_tools(agent_context))

    # Super agent gets its own administrative built-in tools
    if agent.get('is_super'):
        from backend.tools.super_agent_tools import get_super_agent_tool_defs
        tools.extend(get_super_agent_tool_defs())

    # Agent messaging tools — available to super agent and agents with messaging enabled
    if agent.get('is_super') or agent.get('agent_messaging_enabled') != 0:
        from backend.tools.agent_messaging import get_agent_messaging_tool_defs
        tools.extend(get_agent_messaging_tool_defs())

    # Add assigned tools from the registry (including skill tools)
    assigned_ids = set(db.get_agent_tools(agent['id']))
    if assigned_ids:
        seen_fn_names = set()
        for tool_def in tool_registry.get_all_tool_defs():
            tool_id = tool_def.get('id', '')
            fn_name = tool_def.get('function', {}).get('name', '')
            # Match by namespaced id OR bare function name (backward compat)
            if tool_id in assigned_ids or fn_name in assigned_ids:
                # One function name per agent — skip duplicates
                if fn_name in seen_fn_names:
                    continue
                seen_fn_names.add(fn_name)
                tools.append({
                    "type": "function",
                    "function": tool_def['function']
                })

    return tools


def get_compiled_context(agent_id: str) -> dict:
    """Return the compiled system prompt and tool definitions for an agent."""
    agent = db.get_agent(agent_id)
    if not agent:
        return {"system_prompt": "", "tools": []}
    return {
        "system_prompt": build_system_prompt(agent),
        "tools": build_tools(agent)
    }


def build_message_entry(msg: dict, agent: dict) -> dict:
    """Convert a DB message row into an LLM message dict."""
    entry = {"role": msg['role']}
    msg_image = None
    if msg.get('metadata') and isinstance(msg['metadata'], dict):
        msg_image = msg['metadata'].get('image_url')
    if msg_image and agent.get('vision_enabled'):
        parts = []
        if msg.get('content') and msg['content'] != '[Image]':
            parts.append({"type": "text", "text": msg['content']})
        parts.append({"type": "image_url", "image_url": {"url": msg_image}})
        if not parts[0].get('text') if parts else True:
            parts.insert(0, {"type": "text", "text": "What is in this image?"})
        entry['content'] = parts
    elif msg.get('content'):
        content = msg['content']
        # Safety net: re-truncate legacy DB entries that were stored untruncated
        if msg.get('role') == 'tool' and len(content) > MAX_TOOL_RESULT_CHARS:
            remaining = len(content) - MAX_TOOL_RESULT_CHARS
            content = (content[:MAX_TOOL_RESULT_CHARS] +
                       f"\n...[truncated — {remaining} chars omitted]")
        entry['content'] = content
    if msg.get('tool_calls'):
        entry['tool_calls'] = msg['tool_calls']
    if msg.get('tool_call_id'):
        entry['tool_call_id'] = msg['tool_call_id']
    return entry
