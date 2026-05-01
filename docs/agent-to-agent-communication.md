# Agent-to-Agent Communication

## Overview

Agents can send messages to each other, check for replies, escalate approvals to the human user, and resolve safety-check approvals — all without requiring a human in the loop for every step.

## Architecture

### Session Model

All messages between Agent A and Agent B live in **one session** stored in the **session initiator's** (B's) per-agent DB:

```
User → Agent A → send_agent_message("agent_b", "do X")
                         ↓
              Session created in B's DB
              external_user_id = "__agent__<A_id>"
              channel_id = None
```

The `__agent__<id>` prefix on `external_user_id` identifies inter-agent sessions throughout the codebase.

### Session DB Routing: `session_db_agent_id`

`agent_id` was previously overloaded for two purposes:
1. **Processing identity** — which agent runs (system prompt, tools, model)
2. **DB routing** — which per-agent SQLite DB owns the session

These are now separated via `session_db_agent_id` in `_QueueTask`, `_do_process_inner`, and `run_tool_loop`. When an agent processes a session it does not own:

```python
db_agent_id = session_db_agent_id or agent_id
# All db.get_session_messages / db.add_chat_message use db_agent_id
# All agent config ops (get_agent_tools, get_agent_variables, etc.) use agent_id
```

### Key Files

| File | Role |
|------|------|
| `backend/tools/agent_messaging.py` | Tool definitions and executors |
| `backend/agent_runtime/runtime.py` | `process_in_session()`, `_QueueTask.session_db_agent_id`, `_do_process_inner` DB routing |
| `backend/agent_runtime/llm_loop.py` | `run_tool_loop(session_db_agent_id=)`, approval notify |
| `backend/agent_runtime/notifier.py` | `notify_agent()` — routing fixed for `channel_id=None` |

---

## Tools

All tools are available to the super agent by default, and to any agent with `agent_messaging_enabled = 1` in the agents table.

### `send_agent_message`

Send a message to another agent. Delivered asynchronously.

```
send_agent_message(target_agent_id, message)
```

**Guard rails:**
- Self-messaging blocked
- Rate limit: max 10 messages per 60 seconds per (sender, target) pair
- Depth limit: max 5 hops in a chain (prevents A→B→C→D→E→loop)

Internally calls `notify_agent()` with `tag="AGENT/<sender_name>"`, `external_user_id="__agent__<sender_id>"`, `channel_id=None`.

### `check_agent_response`

Check whether the target agent has responded to the last message you sent.

```
check_agent_response(target_agent_id)
```

Anchors to the `id` of the last `[AGENT/<sender_name>]` user message sent by the caller. Only returns assistant messages with a higher `id` (i.e. after that message). Returns `"Agent has not responded yet."` if no reply exists yet.

### `escalate_to_user`

Forward a message to the calling agent's most recent human user session. Use when the agent needs human input while processing inside an inter-agent session.

```
escalate_to_user(message)
```

- Only valid when `agent_context['user_id'].startswith('__agent__')` (i.e. currently in an inter-agent session)
- Uses `db.get_latest_human_session(agent_id)` to find the most recent non-agent, non-scheduler session
- Sends via `notify_agent(trigger_llm=False)` — saves to DB and emits SSE so the human sees it, but does not trigger another LLM turn

### `resolve_agent_approval`

Approve or reject a pending safety-check approval from an agent you messaged.

```
resolve_agent_approval(approval_id, decision)  # decision: "approve" | "reject"
```

Calls `approval_registry.resolve(approval_id, decision)` directly. The `approval_id` is included in the approval notification message.

---

## Approval Escalation Flow

When Agent B needs a safety-check approval while processing a message from Agent A:

```
Agent A → send_agent_message(B, "delete file X")
Agent B: bash(rm X) → requires_approval
  ↓
Writes notification directly into session A-B (B's DB):
  [AGENT/Agent B] Approval required...
  Tool: bash, Risk: high, approval_id: abc-123
  Use resolve_agent_approval to approve or reject.
  ↓
Calls process_in_session(processing_agent_id=A, session_id=..., session_db_agent_id=B)
  ↓
Agent A processes from session A-B — sees full conversation history
  ↓
  Option 1: A can decide → resolve_agent_approval("abc-123", "approve")
  Option 2: A unsure   → escalate_to_user("Agent B needs approval for rm X, ok?")
                              ↓
                         Message appears in user's session with Agent A
                         User responds "ok"
                              ↓
                         A calls resolve_agent_approval("abc-123", "approve")
  ↓
Agent B unblocked, continues execution
```

### Why one session?

Previously two sessions were created:
- A→B in B's DB
- B→A (approval) in A's DB — no context from the original task

Now everything stays in one session in B's DB. When A processes B's approval request, it reads the full history: A's original instruction → B's tool calls → B's approval request. A has full context to decide.

---

## Inter-Agent Session Context Injection

When an agent processes an inter-agent session, a system message is automatically prepended to the conversation:

**Normal case (B processing its own session, A is the sender):**
```
## Inter-Agent Session
You are currently in a private session with another agent: **Agent A** (id: `<id>`).
This is NOT a session with a human user.
If you receive an approval request or need human input,
use the escalate_to_user tool to forward the request to your human user session.
```

**Cross-agent processing (A processing B's session for approval):**
```
## Inter-Agent Session (Cross-Agent Processing)
You are processing a shared session owned by **Agent B** (id: `<id>`).
The full conversation history is visible above — use it as context for your response.
This is NOT a session with a human user.
If you need human input, use the escalate_to_user tool.
```

---

## DB Helper: `get_latest_human_session`

Added to `AgentChatDB` and delegated via `ChatDelegationMixin`:

```python
db.get_latest_human_session(agent_id)
# Returns the most recent non-archived session where:
#   external_user_id NOT LIKE '__agent__%'
#   AND external_user_id != '__scheduler__'
# Ordered by updated_at DESC
```

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `agent_messaging_enabled` | `0` | Enable agent messaging tools for a non-super agent |

Super agent always has all messaging tools enabled.

To enable for a regular agent, set `agent_messaging_enabled = 1` in the agents table (can be done via the super agent's `update_agent` tool).
