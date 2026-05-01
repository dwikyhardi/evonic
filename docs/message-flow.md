  ┌──────────────────────────────────────────────────────────┐
  │                    TELEGRAM USER                         │
  │                  sends a message                         │
  └──────────────────────┬───────────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  backend/channels/telegram.py                            │
  │  handle_message()                                        │
  │  • Extract user_id, text, images                         │
  │  • Get/create session via db.get_or_create_session()     │
  │  • Check bot enabled for session                         │
  │  (typing indicator NOT sent here — moved to _do_process) │
  └──────────────────────┬───────────────────────────────────┘
                         │ calls agent_runtime.handle_message()
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  backend/agent_runtime.py                                │
  │  handle_message()                                        │
  │  • Save user message to DB                               │
  │  • event_stream.emit('message_received')                 │
  │  • Check buffer_seconds → queue task or buffer           │
  └──────────────────────┬───────────────────────────────────┘
                         │ task placed in queue
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  backend/agent_runtime.py                                │
  │  _worker()  ← background thread                          │
  │  • Dequeue task                                          │
  │  • Call _process_and_respond()                           │
  └──────────────────────┬───────────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  _do_process()                                           │
  │  • Send typing indicator via channel  ◄── HERE           │
  │  • event_stream.emit('processing_started')               │
  │  • Build system prompt                                   │
  │  • Load chat history                                     │
  │  • Build tool definitions                                │
  └──────────────────────┬───────────────────────────────────┘
                         │ calls _run_tool_loop()
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  _run_tool_loop()                                        │
  │  • llm_client.chat_completion()  ← LLM CALL              │
  │  • event_stream.emit('llm_thinking') if thinking         │
  │  • event_stream.emit('llm_response_chunk')               │
  │  • If tool calls:                                        │
  │      execute tool → event_stream.emit('tool_executed')   │
  │      → loop back to LLM                                  │
  │  • event_stream.emit('final_answer')                     │
  │  • Return (response_text, tool_trace, timeline)          │
  └──────────────────────┬───────────────────────────────────┘
                         │ returns response
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  _do_process() (continued)                               │
  │  • event_stream.emit('turn_complete')                    │
  │  • Trigger background summarization thread               │
  └──────────────────────┬───────────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  _worker() (continued) — buffered path only              │
  │  • Get channel instance from channel_manager             │
  │  • Call instance.send_message(user_id, response)         │
  └──────────────────────┬───────────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │  backend/channels/telegram.py                            │
  │  send_message()                                          │
  │  • Split message into ≤4096 char chunks                  │
  │  • bot.send_message() for each chunk                     │
  │  • event_stream.emit('message_sent')                     │
  └──────────────────────┬───────────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │                    TELEGRAM USER                         │
  │                  receives reply                          │
  └──────────────────────────────────────────────────────────┘

  Key files:

  ┌────────────────────────────────────┬──────────────────────────────────────┐
  │               File                 │                Role                  │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/channels/telegram.py       │ Receives incoming Telegram message   │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/agent_runtime.py           │ Routes message, queues task          │
  │   handle_message()                 │ emits: message_received              │
  │   _do_process()                    │ sends typing, emits: processing_started│
  │   _run_tool_loop()                 │ emits: llm_thinking, llm_response_   │
  │                                    │        chunk, tool_executed,         │
  │                                    │        final_answer, turn_complete   │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/event_stream.py            │ Pub/sub bus — see docs/event-stream  │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/plugin_manager.py          │ Bridges plugins onto event_stream    │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/channels/telegram.py       │ Sends reply, emits: message_sent     │
  │   send_message()                   │                                      │
  ├────────────────────────────────────┼──────────────────────────────────────┤
  │ backend/channels/registry.py       │ Manages channel lifecycle            │
  └────────────────────────────────────┴──────────────────────────────────────┘

  Event stream log: logs/events.log  (configurable via EVENT_LOG_FILE in .env)
  Full event reference: docs/event-stream.md
