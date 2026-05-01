import os
import threading
from datetime import datetime, timezone

_lock = threading.Lock()


def log_api_call(messages, response_text, duration_ms, error=None, log_file=None, thinking=None):
    """Append a markdown block for an LLM API call. No-op when disabled."""
    try:
        from models.db import db as _db
        _enabled = _db.get_setting('llm_api_log_enabled')
        if _enabled is None or _enabled != '1':
            return
        if log_file is None:
            log_file = _db.get_setting('llm_api_log_file')
        if log_file is None:
            return
        target = log_file
    except Exception:
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    est_tokens = sum(len(msg.get("content", "") or "") for msg in messages) // 4

    lines = []
    lines.append(f"## {ts} — {duration_ms}ms (~{est_tokens}tok)")
    if error:
        lines.append(f"**Error:** {error}")
    lines.append("")
    lines.append("### Prompt")
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")

        header = f"**{role}:**"
        if tool_call_id:
            header += f" *(tool_call_id: {tool_call_id})*"
        lines.append(header)

        if tool_calls:
            import json as _json
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                try:
                    args = _json.loads(fn.get("arguments", "{}"))
                    args_str = _json.dumps(args, ensure_ascii=False)
                except Exception:
                    args_str = fn.get("arguments", "")
                lines.append(f"[tool_call] **{name}**({args_str})")
        if content:
            lines.append(content)
        lines.append("")
    if thinking:
        lines.append("### Thinking")
        lines.append(thinking)
        lines.append("")
    lines.append("### Response")
    lines.append(response_text or "(empty)")
    lines.append("")
    lines.append("---")
    lines.append("")

    try:
        with _lock:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
    except Exception:
        pass
