# Chat Log Format (JSONL)

Each agent's chat history is stored in an append-only JSONL file at:
```
agents/<agent_id>/chat.jsonl
```

Every line is a valid JSON object representing a single chat event. Lines are written in real time as events occur, so the file is strictly ordered by `ts` (epoch milliseconds).

## Required Fields

| Field | Type | Description |
|---|---|---|
| `ts` | integer | Unix epoch **milliseconds** |
| `type` | string | Entry type (see table below) |
| `session_id` | string | UUID of the chat session this entry belongs to |

## Entry Types

| Type | Written by | Fields (besides required) |
|---|---|---|
| `user` | runtime.py on message receive | `content`, `sender_id`, `metadata?` |
| `turn_begin` | llm_loop.py at start of LLM processing | — |
| `thinking` | llm_loop.py when reasoning is extracted | `content` |
| `tool_call` | llm_loop.py for each tool invocation | `function`, `params`, `id` |
| `tool_output` | llm_loop.py after each tool returns | `content`, `tool_call_id`, `error` |
| `intermediate` | llm_loop.py for non-final assistant text | `content` |
| `final` | llm_loop.py for the turn's final response | `content`, `metadata?` |
| `turn_end` | llm_loop.py at end of each turn | `thinking_duration?` |
| `pending` | (reserved) queued user message | `content`, `sender_id` |
| `system` | runtime.py for slash-command responses, stop injections | `content`, `metadata?` |
| `error` | llm_loop.py on LLM error or loop termination | `content`, `metadata?` |

## Pairing Rule

Every `tool_output` entry has a `tool_call_id` that matches the `id` of the corresponding `tool_call` entry. Use this to associate results with invocations regardless of position.

## Example Entries

```json
{"ts": 1746000000000, "type": "user", "session_id": "abc-123", "content": "Hello!", "sender_id": "user_456"}
{"ts": 1746000000100, "type": "turn_begin", "session_id": "abc-123"}
{"ts": 1746000001000, "type": "thinking", "session_id": "abc-123", "content": "The user said hello..."}
{"ts": 1746000001500, "type": "tool_call", "session_id": "abc-123", "function": "search_docs", "params": {"query": "hello"}, "id": "tc-xyz"}
{"ts": 1746000002000, "type": "tool_output", "session_id": "abc-123", "content": "{\"results\": []}", "tool_call_id": "tc-xyz", "error": false}
{"ts": 1746000003000, "type": "final", "session_id": "abc-123", "content": "Hi there!", "metadata": {"thinking_duration": 3.0}}
{"ts": 1746000003100, "type": "turn_end", "session_id": "abc-123", "thinking_duration": 3.0}
```

## Pagination API

```
GET /api/agents/<agent_id>/chat?session_id=<sid>&limit=15
```
Returns the **tail** (last 15 entries) ordered by `ts` ascending.

```
GET /api/agents/<agent_id>/chat?session_id=<sid>&to_ts=<epoch_ms>&limit=15
```
Returns up to 15 entries with `ts < to_ts` — use `ts` of the oldest currently-loaded entry as `to_ts` to walk backwards.

```
GET /api/agents/<agent_id>/chat?session_id=<sid>&after_ts=<epoch_ms>&limit=50
```
Returns entries with `ts > after_ts` — use for forward polling (new events since last seen).

Response shape:
```json
{"entries": [...], "has_more": true}
```
`has_more` is `true` when the returned count equals `limit`, signalling there may be more.

## Implementation Notes

- One file per agent; entries from multiple sessions are interleaved (filter by `session_id`).
- Tail reads use a reverse byte-scan in 8KB chunks — fast even for large files.
- All writes use a per-agent `threading.Lock`; the file handle stays open in append mode.
- Live events still flow through the SSE `event_stream` during an active turn; JSONL provides
  persistence so the correct order is recovered after a browser refresh.
