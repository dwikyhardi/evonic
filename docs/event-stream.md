# Event Stream

`backend/event_stream.py` is a lightweight, standalone pub/sub event bus used
throughout the agent runtime. It replaces direct calls to `plugin_manager.dispatch()`
so that internal components (typing indicators, logging) and plugins are equal,
decoupled consumers of the same event flow.

## API

```python
from backend.event_stream import event_stream

# Subscribe
event_stream.on('processing_started', my_handler)

# Unsubscribe
event_stream.off('processing_started', my_handler)

# Emit (non-blocking — handlers run in a thread pool)
event_stream.emit('processing_started', {'agent_id': ..., ...})
```

Handlers are called asynchronously in a `ThreadPoolExecutor` (4 workers).
Errors inside handlers are caught and logged; they never propagate to the caller.

## Log File

Every `emit()` call writes a timestamped line to `logs/events.log`:

```
[2026-04-12 10:23:01.432] processing_started | agent_id=krasan, channel_id=telegram, ...
[2026-04-12 10:23:03.812] llm_thinking | thinking=The user is asking about...
[2026-04-12 10:23:04.210] final_answer | answer=Halo! Saya bisa bantu...
[2026-04-12 10:23:04.410] message_sent | channel_type=telegram, external_user_id=76639539
```

The log file path is configurable via `EVENT_LOG_FILE` in `.env`
(default: `logs/events.log`). Use `tail -f logs/events.log` to follow it live.

## Events Reference

### `message_received`
Emitted in `handle_message()` right after the user message is saved to the DB,
before any LLM processing begins.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | Agent handling the message |
| `agent_name` | str | Human-readable agent name |
| `session_id` | str | Session UUID |
| `external_user_id` | str | Platform user ID (e.g. Telegram chat ID) |
| `channel_id` | str | Channel UUID |
| `message` | str | User message text |
| `image_url` | str\|None | Base64 data URL for vision messages |

---

### `processing_started`
Emitted at the very top of `_do_process()`, right before the system prompt is
built and the LLM is called. The typing indicator is sent at this point.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `agent_name` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |

---

### `llm_thinking`
Emitted when the LLM response contains a reasoning/thinking block
(`reasoning_content` field or `<think>` / `<|channel>thought` tags).

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |
| `thinking` | str | Extracted thinking content |

---

### `llm_response_chunk`
Emitted for every content block extracted from an LLM response, including
intermediate content before tool calls.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |
| `content` | str | LLM text output |
| `is_final` | bool | `True` if no tool calls follow (final answer turn) |

---

### `tool_executed`
Emitted after each tool call inside the tool loop, once the result is available.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |
| `tool_name` | str | Function name called |
| `tool_args` | dict | Arguments passed to the tool |
| `tool_result` | dict | Result returned by the tool |
| `has_error` | bool | `True` if result contains an `error` key |

---

### `final_answer`
Emitted inside `_run_tool_loop()` immediately before returning the final
response to the caller. At this point the answer has been saved to the DB.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |
| `answer` | str | Final response text sent to the user |
| `tool_trace` | list | List of `{tool, args, result}` dicts |
| `timeline` | list | Chronological list of thinking/tool/response events |

---

### `turn_complete`
Emitted at the end of `_do_process()`, after the final answer is returned.
This is the last event per turn and is also the trigger for plugins
(e.g. `session-recap`) that need the full result.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `agent_name` | str | |
| `session_id` | str | |
| `external_user_id` | str | |
| `channel_id` | str | |
| `response` | str | Final response text |
| `tool_trace` | list | |
| `is_error` | bool | `True` if the turn ended in an LLM error |

---

### `message_sent`
Emitted by `TelegramChannel` after the reply has been successfully delivered.
Fired in both the direct reply path (non-buffered) and `send_message()` (buffered).

| Field | Type | Description |
|---|---|---|
| `channel_type` | str | e.g. `"telegram"` |
| `channel_id` | str | |
| `external_user_id` | str | |
| `message` | str | The exact text delivered to the user |

---

### `summary_updated`
Emitted by `_do_summarize()` when a session summary is successfully written to
the DB. Used by the `session-recap` plugin.

| Field | Type | Description |
|---|---|---|
| `agent_id` | str | |
| `agent_name` | str | |
| `session_id` | str | |
| `summary` | str | Full summary text |
| `last_message_id` | int | DB ID of the last message covered |
| `message_count` | int | Number of messages summarized |
| `tail_messages` | list | Unsummarized recent messages `[{role, content}]` |

## Event Ordering Per Turn

```
message_received
    └─ processing_started          ← typing indicator sent here
           └─ [for each LLM call]
                  ├─ llm_thinking?
                  ├─ llm_response_chunk
                  └─ [for each tool call]
                         └─ tool_executed
           └─ final_answer
    └─ turn_complete
    └─ message_sent                ← after channel delivery
```

Background (may fire later, on a separate thread):
```
summary_updated                    ← if summarization threshold reached
```

## SSE — Browser Real-time Stream

### Endpoint

```
GET /api/agents/<agent_id>/chat/stream?session_id=<uuid>
```

Implemented in `routes/agents.py`. Opens a persistent HTTP connection that pushes
live events for one session to the browser via Server-Sent Events (SSE). The
connection closes automatically when a `done` event is received or after 120 s of
inactivity.

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

### Internal → SSE Event Mapping

| Internal event | SSE event name | Payload forwarded to browser |
|---|---|---|
| `llm_thinking` | `thinking` | `{ "content": "<thinking text>" }` |
| `tool_executed` | `tool_executed` | `{ "tool", "args", "result", "error" }` |
| `llm_response_chunk` | `response_chunk` | `{ "content", "is_final" }` |
| `turn_complete` | `done` | `{}` |

Events are filtered by `session_id` — each SSE connection only receives events for
its own session. The internal queue is capped at 200 items; excess events are
silently dropped.

### Browser Usage

```javascript
const source = new EventSource(
  `/api/agents/${agentId}/chat/stream?session_id=${sessionId}`
);

source.addEventListener('thinking', e => {
  const { content } = JSON.parse(e.data);
  // show thinking bubble
});

source.addEventListener('tool_executed', e => {
  const { tool, args, result, error } = JSON.parse(e.data);
  // append timeline entry
});

source.addEventListener('response_chunk', e => {
  const { content, is_final } = JSON.parse(e.data);
  // stream text to UI
});

source.addEventListener('done', () => {
  source.close();
});
```

The production implementation lives in `static/js/chat-ui.js` (`connectThinkingStream()`).

---

## Plugin Integration

The `PluginManager` subscribes to the event stream automatically when a plugin
is loaded. Each event listed in `plugin.json` `events` array gets a bridge
closure registered on `event_stream`. When the event fires, the bridge:

1. Checks the global `events_dispatch_enabled` kill switch
2. Logs the event payload to the plugin's in-memory ring buffer
3. Creates a `PluginSDK` instance
4. Submits the handler to the plugin executor thread pool

Plugins do not need to interact with `event_stream` directly — they subscribe
via `plugin.json` as before. The bridge is transparent.

To add a new event that plugins can subscribe to, add the name to `VALID_EVENTS`
in `backend/plugin_manager.py` (for documentation; it is not enforced).
