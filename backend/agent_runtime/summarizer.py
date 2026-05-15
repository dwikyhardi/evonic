"""
summarizer.py — background conversation summarization pipeline.

Self-contained: chunked LLM summarization, DB persistence, recap log writing.
"""

import os
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from models.db import db
from backend.llm_client import llm_client, strip_thinking_tags
from config import AGENT_MAX_SUMMARIZE_BATCH as MAX_SUMMARIZE_BATCH

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOGS_DIR = os.path.join(_BASE_DIR, 'logs')


def _recap_log_path(agent_id: str) -> str:
    return os.path.join(_LOGS_DIR, 'agents', agent_id, 'sessrecap.log')


def _current_datetime_str() -> str:
    gmt7 = timezone(timedelta(hours=7))
    now = datetime.now(gmt7)
    return now.strftime('%A, %Y-%m-%d, %H:%M:%S (WIB/UTC+7)')


DEFAULT_SUMMARIZE_PROMPT = """You are a conversation summarizer. Create a factual summary of a conversation between a user and an AI assistant.

Current date/time: {current_datetime}

Rules:
- Write in English only, regardless of the conversation language
- Extract ONLY facts, decisions, requests, and outcomes
- Do NOT include any style, tone, greetings, emojis, or honorifics
- Use bullet points for clarity
- If there is an existing summary, merge then create new compact summary
- Ignore the tools, focus to the agent response and user decision.
- Keep the summary concise but complete — no information loss.
- You **MUST KEEP** the user information that already provided or known like phone number, full name, contact person if any.

## Summary Example:
- User Information:
    - Full Name: ...
    - Phone Number: ...
    - Total Guests: ...
- Requests:
    - ...
    - ...
- Follow up:
    - ...
- Issues: <-- notes if user complaint, angry, frustrated, encounter error, or confused, format: issue description. agent response: xxx.
    - ...
- Facts:
    - ...

{existing_summary_section}

Messages to summarize:
{messages_text}

Write the updated factual summary:"""


def maybe_summarize(agent: dict, session_id: str,
                    summarize_guard: threading.Lock,
                    summarize_active: set,
                    llm_lock: threading.Lock) -> None:
    """Concurrency guard: prevents duplicate summarization for the same session."""
    # LOCK ORDERING: _summarize_guard → llm_lock. _summarize_guard is acquired
    # first (here), then llm_lock is acquired inside the summarization call.
    # Never reverse this order.
    with summarize_guard:
        if session_id in summarize_active:
            return
        summarize_active.add(session_id)
    try:
        _do_summarize(agent, session_id, llm_lock)
    except Exception as e:
        print(f"[AgentRuntime] Summarization error (non-fatal): {e}")
    finally:
        with summarize_guard:
            summarize_active.discard(session_id)


def _do_summarize(agent: dict, session_id: str, llm_lock: threading.Lock) -> None:
    """Core summarization logic with chunking and truncation protection."""
    from models.chatlog import chatlog_manager, _SUMMARY_COUNT_TYPES
    agent_id = agent['id']
    threshold = agent.get('summarize_threshold', 3)
    tail_size = agent.get('summarize_tail', 5)

    chatlog = chatlog_manager.get(agent_id, session_id)
    _has_jsonl = chatlog.get_last_entry() is not None

    if _has_jsonl:
        _do_summarize_jsonl(agent, session_id, llm_lock, chatlog,
                            threshold, tail_size, _SUMMARY_COUNT_TYPES)
    else:
        _do_summarize_sqlite(agent, session_id, llm_lock, threshold, tail_size)


def _do_summarize_jsonl(agent: dict, session_id: str, llm_lock: threading.Lock,
                        chatlog, threshold: int, tail_size: int,
                        summary_count_types) -> None:
    """Summarize using JSONL as the message source."""
    agent_id = agent['id']

    total = chatlog.count_entries(types=summary_count_types)
    if total < threshold:
        return

    summary_record = db.get_summary(session_id, agent_id=agent_id)

    # Get all conversation entries (user, final, intermediate) for cut-point calculation
    all_entries = chatlog.get_all_for_session(types=summary_count_types)
    if len(all_entries) <= tail_size:
        return

    # Cut: summarize everything except the last tail_size entries
    cut_index = len(all_entries) - tail_size
    # Don't split a user-assistant pair at the cut
    if cut_index > 0 and all_entries[cut_index - 1].get('type') == 'user':
        cut_index -= 1
    if cut_index <= 0:
        return

    last_summarized_entry = all_entries[cut_index - 1]
    new_last_ts = last_summarized_entry['ts']

    # Skip if summary already covers this point
    if summary_record and (summary_record.get('last_message_ts') or 0) >= new_last_ts:
        return

    # Get entries to fold into summary
    if summary_record and summary_record.get('last_message_ts'):
        entries_to_summarize = chatlog.get_entries_between_ts(
            summary_record['last_message_ts'],
            new_last_ts,
        )
        entries_to_summarize = [e for e in entries_to_summarize
                                 if e.get('type') in summary_count_types]
        existing_summary = summary_record['summary']
    else:
        entries_to_summarize = all_entries[:cut_index]
        existing_summary = None

    if not entries_to_summarize:
        return

    prompt_template = agent.get('summarize_prompt') or DEFAULT_SUMMARIZE_PROMPT

    chunks = [entries_to_summarize[i:i + MAX_SUMMARIZE_BATCH]
              for i in range(0, len(entries_to_summarize), MAX_SUMMARIZE_BATCH)]

    current_summary = existing_summary
    summarized_up_to_ts = (summary_record.get('last_message_ts') or 0) if summary_record else 0
    summarized_count = summary_record['message_count'] if summary_record else 0

    for chunk in chunks:
        messages_text = _format_entries_for_summary(chunk)
        existing_section = f"Existing summary to update:\n{current_summary}\n" if current_summary else ""

        prompt = prompt_template.format(
            existing_summary_section=existing_section,
            messages_text=messages_text,
            current_datetime=_current_datetime_str()
        )

        # LOCK ORDERING: llm_lock is acquired inside the summarization path,
        # always AFTER _summarize_guard (held by caller maybe_summarize).
        with llm_lock:
            result = llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.0,
                enable_thinking=False,
                max_tokens=None
            )

        if not result.get('success'):
            print(f"[AgentRuntime] Summarize LLM failed: {result.get('error_type', 'unknown')}")
            break

        choice = result['response'].get('choices', [{}])[0]
        if choice.get('finish_reason') == 'length':
            print(f"[AgentRuntime] Summary truncated (finish_reason=length), skipping chunk")
            break

        summary_text = choice.get('message', {}).get('content', '')
        if not summary_text:
            break

        summary_text, _ = strip_thinking_tags(summary_text)
        current_summary = summary_text
        summarized_up_to_ts = chunk[-1]['ts']
        summarized_count += len(chunk)

    if current_summary and summarized_up_to_ts > ((summary_record.get('last_message_ts') or 0) if summary_record else 0):
        db.upsert_summary(session_id, current_summary, 0,
                          summarized_count, agent_id=agent_id,
                          last_message_ts=summarized_up_to_ts)

        try:
            recap_path = _recap_log_path(agent_id)
            os.makedirs(os.path.dirname(recap_path), exist_ok=True)
            ts_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            recap_entry = (
                f"## {ts_str} — session={session_id} msgs_covered={summarized_count} "
                f"last_msg_ts={summarized_up_to_ts}\n"
                f"{current_summary}\n\n---\n\n"
            )
            with open(recap_path, 'a', encoding='utf-8') as f:
                f.write(recap_entry)
        except Exception as e:
            print(f"[AgentRuntime] sessrecap log write failed (non-fatal): {e}")

        from backend.event_stream import event_stream
        tail_entries = all_entries[cut_index:]
        tail_messages = [{'role': 'user' if e['type'] == 'user' else 'assistant',
                          'content': e.get('content', '')}
                         for e in tail_entries]
        event_stream.emit('summary_updated', {
            'agent_id': agent_id,
            'agent_name': agent.get('name', ''),
            'session_id': session_id,
            'summary': current_summary,
            'last_message_id': 0,
            'message_count': summarized_count,
            'tail_messages': tail_messages,
        })


def _do_summarize_sqlite(agent: dict, session_id: str, llm_lock: threading.Lock,
                         threshold: int, tail_size: int) -> None:
    """Summarize using SQLite as the message source (pre-JSONL fallback)."""
    agent_id = agent['id']

    total = db.get_message_count(session_id, agent_id=agent_id)
    if total < threshold:
        return

    summary_record = db.get_summary(session_id, agent_id=agent_id)

    all_messages = db.get_session_messages(session_id, limit=9999, agent_id=agent_id)
    if len(all_messages) <= tail_size:
        return

    cut_index = len(all_messages) - tail_size
    cut_index = _adjust_cut_for_tool_chain(all_messages, cut_index)
    if cut_index > 0 and all_messages[cut_index - 1].get('role') == 'user':
        cut_index -= 1
    if cut_index <= 0:
        return

    last_summarized_msg = all_messages[cut_index - 1]
    new_last_message_id = last_summarized_msg['id']

    if summary_record and summary_record['last_message_id'] >= new_last_message_id:
        return

    if summary_record:
        msgs_to_summarize = db.get_messages_between(
            session_id, summary_record['last_message_id'],
            new_last_message_id, agent_id=agent_id)
        existing_summary = summary_record['summary']
    else:
        msgs_to_summarize = all_messages[:cut_index]
        existing_summary = None

    if not msgs_to_summarize:
        return

    prompt_template = agent.get('summarize_prompt') or DEFAULT_SUMMARIZE_PROMPT

    chunks = [msgs_to_summarize[i:i + MAX_SUMMARIZE_BATCH]
              for i in range(0, len(msgs_to_summarize), MAX_SUMMARIZE_BATCH)]

    current_summary = existing_summary
    summarized_up_to = summary_record['last_message_id'] if summary_record else 0
    summarized_count = summary_record['message_count'] if summary_record else 0

    for chunk in chunks:
        messages_text = _format_messages_for_summary(chunk)
        existing_section = f"Existing summary to update:\n{current_summary}\n" if current_summary else ""

        prompt = prompt_template.format(
            existing_summary_section=existing_section,
            messages_text=messages_text,
            current_datetime=_current_datetime_str()
        )

        # LOCK ORDERING: llm_lock is acquired inside the summarization path,
        # always AFTER _summarize_guard (held by caller maybe_summarize).
        with llm_lock:
            result = llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.0,
                enable_thinking=False,
                max_tokens=None
            )

        if not result.get('success'):
            print(f"[AgentRuntime] Summarize LLM failed: {result.get('error_type', 'unknown')}")
            break

        choice = result['response'].get('choices', [{}])[0]
        if choice.get('finish_reason') == 'length':
            print(f"[AgentRuntime] Summary truncated (finish_reason=length), skipping chunk")
            break

        summary_text = choice.get('message', {}).get('content', '')
        if not summary_text:
            break

        summary_text, _ = strip_thinking_tags(summary_text)
        current_summary = summary_text
        summarized_up_to = chunk[-1]['id']
        summarized_count += len(chunk)

    if current_summary and summarized_up_to > (summary_record['last_message_id'] if summary_record else 0):
        db.upsert_summary(session_id, current_summary, summarized_up_to,
                          summarized_count, agent_id=agent_id)

        try:
            recap_path = _recap_log_path(agent_id)
            os.makedirs(os.path.dirname(recap_path), exist_ok=True)
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            recap_entry = (
                f"## {ts} — session={session_id} msgs_covered={summarized_count} "
                f"last_msg_id={summarized_up_to}\n"
                f"{current_summary}\n\n---\n\n"
            )
            with open(recap_path, 'a', encoding='utf-8') as f:
                f.write(recap_entry)
        except Exception as e:
            print(f"[AgentRuntime] sessrecap log write failed (non-fatal): {e}")

        from backend.event_stream import event_stream
        tail_messages = [{'role': m['role'], 'content': m.get('content', '')}
                         for m in all_messages[cut_index:]]
        event_stream.emit('summary_updated', {
            'agent_id': agent_id,
            'agent_name': agent.get('name', ''),
            'session_id': session_id,
            'summary': current_summary,
            'last_message_id': summarized_up_to,
            'message_count': summarized_count,
            'tail_messages': tail_messages,
        })


def _adjust_cut_for_tool_chain(messages: list, cut_index: int) -> int:
    """Move cut_index backwards to avoid splitting a tool call chain."""
    if cut_index <= 0 or cut_index >= len(messages):
        return cut_index
    while cut_index > 0:
        msg = messages[cut_index]
        if msg['role'] == 'tool':
            cut_index -= 1
            continue
        if msg['role'] == 'assistant' and msg.get('tool_calls'):
            cut_index -= 1
            continue
        break
    return cut_index


def _format_messages_for_summary(messages: list) -> str:
    """Format messages into a readable text block for the summarization LLM."""
    lines = []
    for msg in messages:
        role = msg['role'].upper()
        content = msg.get('content', '') or ''
        # NOTE: Tool calls and tool results are excluded from summary to reduce noise.
        # The summary focuses on user/assistant conversation flow only.
        if msg.get('tool_calls') or msg['role'] == 'tool':
            continue
        # Skip legacy agent-state system messages stored in chat_messages (pre-migration)
        meta = msg.get('metadata')
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = None
        if isinstance(meta, dict) and meta.get('agent_state'):
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _format_entries_for_summary(entries: list) -> str:
    """Format JSONL entries into a readable text block for the summarization LLM."""
    lines = []
    for entry in entries:
        etype = entry.get('type', '')
        content = entry.get('content', '') or ''
        if etype == 'user':
            lines.append(f"USER: {content}")
        elif etype in ('final', 'intermediate'):
            lines.append(f"ASSISTANT: {content}")
        # Other types (thinking, tool_call, tool_output, system, error, etc.) are skipped
    return "\n".join(lines)
