"""
Caveman — event handlers.
Uses message_interceptor to inject compression rules into LLM context.
"""

import time
import logging

_logger = logging.getLogger(__name__)

# Per-agent state: {agent_id: {"mode": str, "start_time": float, ...}}
_agent_state = {}

# Lifetime stats (persists in memory while plugin is loaded)
_lifetime_stats = {
    "total_output_tokens": 0,
    "total_input_tokens": 0,
    "total_turns": 0,
    "sessions_tracked": 0,
    "mode_switches": 0,
}

MODES = ("off", "lite", "full", "ultra", "wenyan-lite", "wenyan-full", "wenyan-ultra")
DEFAULT_MODE = "full"
TRACK_STATS = True

CAVEMAN_RULES = {
    "lite": """CAVEMAN MODE: LITE
Rules:
- No filler words, hedging, or softening phrases
- Keep articles (a, the) and full sentence structure
- Professional tone, just tighter
- Cut pleasantries and restatements of the question
- One shot. No "great question" or "let me explain".""",

    "full": """CAVEMAN MODE: FULL (DEFAULT)
Rules:
- Drop articles (a, the, an)
- Fragments OK. Short sentences
- Use short synonyms (use→use, utilize→use, approximately→~)
- No filler, hedging, or softening
- Keep technical terms exact — never abbreviate domain concepts
- Bullets over prose when listing
- No restating the question
- One shot. No "great question".""",

    "ultra": """CAVEMAN MODE: ULTRA
Rules:
- Drop articles, pronouns (it, that, this) when context obvious
- Abbreviate common prose words: because→bc, without→w/o, with→w/, before→b4, about→abt, between→btwn
- Tech abbreviations OK: DB, auth, config, req, res, fn, impl, ctx, env, var, str, int, bool, err, msg, val, ref, ptr
- Strip conjunctions (and→comma, but→however period)
- Arrows for causality: → for "leads to" / "causes"
- Fragments expected. Telegram style
- Keep all technical terms recognizable — no invented abbreviations
- Auto-clarity: drop ultra mode for security warnings or irreversible actions.""",

    "wenyan-lite": """CAVEMAN MODE: WENYAN-LITE
Style: Classical Chinese (文言文) lite compression.
Rules:
- Use classical Chinese sentence particles sparingly: 也, 矣, 乎
- Short phrases over full sentences
- Mix modern and classical vocabulary
- Compress common expressions: 然而 → 然, 因为 → 因, 所以 → 故
- Keep technical terms in English
- Professional but compressed.""",

    "wenyan-full": """CAVEMAN MODE: WENYAN-FULL
Style: Classical Chinese (文言文) full compression.
Rules:
- Classical particles: 也, 矣, 乎, 哉, 耳
- Subject-verb-object compressed to essential characters
- Drop connectives where context clear
- 故 for "therefore", 然 for "however", 若 for "if"
- Tech terms stay in English
- Fragments, telegraphic style.""",

    "wenyan-ultra": """CAVEMAN MODE: WENYAN-ULTRA
Style: Classical Chinese (文言文) maximum compression.
Rules:
- Minimal characters per concept
- Classical grammar only
- Tech terms abbreviated even in English
- Only most essential information preserved
- Use for quick status updates and code snippets.""",
}

# Command response messages (pre-computed)
_CMD_RESPONSES = {
    "activated": "Caveman mode activated: {mode}. Ugh ugh.",
    "deactivated": "Caveman mode deactivated. Normal speech resumed.",
    "mode_set": "Caveman mode set: {mode}.",
    "unknown_mode": "Unknown mode: {mode}. Valid: {valid}.",
    "sub_skill": "Caveman {action} ready. Paste your text/code.",
}


def _get_agent_state(agent_id, sdk=None):
    if agent_id not in _agent_state:
        default = "off"
        if sdk:
            cfg = sdk.config.get("DEFAULT_MODE", DEFAULT_MODE)
            if cfg in MODES:
                default = cfg
        _agent_state[agent_id] = {
            "mode": "off",
            "start_time": time.time(),
            "output_tokens": 0,
            "input_tokens": 0,
            "turns": 0,
            "mode_switches": 0,
        }
    return _agent_state[agent_id]


def _handle_command(text, agent_id):
    """Parse caveman commands. Returns (handled: bool, response: str|None)."""
    t = text.strip().lower()

    # /caveman on or just /caveman
    if t in ("/caveman", "/caveman on", "caveman mode"):
        s = _get_agent_state(agent_id)
        mode = s.get("_default_mode", DEFAULT_MODE)
        s["mode"] = mode
        _lifetime_stats["mode_switches"] += 1
        s["mode_switches"] += 1
        return True, _CMD_RESPONSES["activated"].format(mode=mode)

    # /caveman <mode>
    if t.startswith("/caveman "):
        mode = t.replace("/caveman ", "").strip()
        if mode in MODES:
            s = _get_agent_state(agent_id)
            if mode == "off":
                s["mode"] = "off"
                return True, _CMD_RESPONSES["deactivated"]
            s["mode"] = mode
            _lifetime_stats["mode_switches"] += 1
            s["mode_switches"] += 1
            return True, _CMD_RESPONSES["mode_set"].format(mode=mode)
        return True, _CMD_RESPONSES["unknown_mode"].format(mode=mode, valid=", ".join(MODES))

    # Off commands
    if t in ("/caveman off", "stop caveman", "normal mode", "turn off caveman"):
        s = _get_agent_state(agent_id)
        s["mode"] = "off"
        return True, _CMD_RESPONSES["deactivated"]

    # Sub-skills
    if t in ("/caveman-commit", "/caveman-review", "/caveman-compress"):
        s = _get_agent_state(agent_id)
        action = t.replace("/caveman-", "")
        s["_pending_action"] = action
        return True, _CMD_RESPONSES["sub_skill"].format(action=action)

    # Stats
    if t == "/caveman-stats":
        s = _get_agent_state(agent_id)
        elapsed = time.time() - s["start_time"]
        mins = int(elapsed / 60)
        lines = [
            "=== CAVEMAN STATS ===",
            f"Mode: {s['mode']}",
            f"Session turns: {s['turns']}",
            f"Session output tokens: {s['output_tokens']}",
            f"Session input tokens: {s['input_tokens']}",
            f"Session mode switches: {s['mode_switches']}",
            f"Session duration: {mins}m",
            "",
            "--- Lifetime ---",
            f"Total turns: {_lifetime_stats['total_turns']}",
            f"Total output tokens: {_lifetime_stats['total_output_tokens']}",
            f"Total input tokens: {_lifetime_stats['total_input_tokens']}",
            f"Sessions tracked: {_lifetime_stats['sessions_tracked']}",
            f"Total mode switches: {_lifetime_stats['mode_switches']}",
        ]
        return True, "\n".join(lines)

    # Help
    if t == "/caveman-help":
        lines = [
            "=== CAVEMAN HELP ===",
            "/caveman — activate default mode",
            "/caveman <mode> — set mode (lite/full/ultra/wenyan-lite/wenyan-full/wenyan-ultra)",
            "/caveman off — deactivate",
            "/caveman-commit — caveman-style commit message",
            "/caveman-review — caveman code review",
            "/caveman-compress — compress text to caveman style",
            "/caveman-stats — show token stats",
            "/caveman-help — this help",
        ]
        return True, "\n".join(lines)

    return False, None


def _message_interceptor(agent_id, content, messages):
    """Inject caveman rules into LLM context.

    Called synchronously in the LLM loop at two points:
    1. Pre-turn (content=''): before first LLM call — detect commands, inject rules
    2. Pre-final (content=...): before final answer — track stats
    """
    # Pre-final: track stats
    if content:
        s = _agent_state.get(agent_id)
        if s and s["mode"] != "off":
            s["turns"] += 1
            _lifetime_stats["total_turns"] += 1
            _lifetime_stats["sessions_tracked"] = len(_agent_state)
        return None

    # Pre-turn: find latest user message
    latest_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            latest_user_msg = msg.get("content", "")
            break

    if not latest_user_msg:
        return None

    # Check if it's a caveman command
    handled, response = _handle_command(latest_user_msg, agent_id)
    if handled and response:
        # Inject a system instruction telling the LLM to respond with the command result
        return {"inject": f"[SYSTEM] Caveman plugin handled a command. Respond to the user with exactly this message, nothing else:\n\n{response}"}

    # Not a command — check if caveman mode is active
    s = _agent_state.get(agent_id)
    if not s or s["mode"] == "off":
        return None

    mode = s["mode"]
    rules = CAVEMAN_RULES.get(mode)
    if not rules:
        return None

    # Inject caveman rules as a system message
    return {"inject": rules}


def on_message_received(event, sdk):
    """Track incoming messages for stats."""
    agent_id = event.get("agent_id", "")
    if not agent_id:
        return

    # Initialize agent state with default mode from config
    s = _get_agent_state(agent_id, sdk)
    s["_default_mode"] = sdk.config.get("DEFAULT_MODE", DEFAULT_MODE)


def on_turn_complete(event, sdk):
    """Track token usage for stats."""
    agent_id = event.get("agent_id", "")
    if not agent_id:
        return

    s = _get_agent_state(agent_id)

    usage = event.get("usage", event.get("token_usage", {}))
    out_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    in_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0

    s["output_tokens"] += out_tokens
    s["input_tokens"] += in_tokens

    _lifetime_stats["total_output_tokens"] += out_tokens
    _lifetime_stats["total_input_tokens"] += in_tokens


def on_final_answer(event, sdk):
    """Log caveman-styled response for stats."""
    agent_id = event.get("agent_id", "")
    s = _agent_state.get(agent_id)

    if not s or s["mode"] == "off":
        return

    sdk.log(f"[caveman] Response generated in {s['mode']} mode for agent {agent_id}")


# ── Register hooks at module load time ──────────────────────────────────

try:
    from backend.plugin_hooks import register_message_interceptor
    register_message_interceptor(_message_interceptor)
    _logger.info("[caveman] Message interceptor registered")
except Exception as e:
    _logger.error("[caveman] Failed to register message interceptor: %s", e)
