# Plugin Creator Skill

## Overview

This skill allows you to scaffold new Evonic plugins directly from a conversation. After creating a plugin, you can edit its generated files to add the actual business logic.

## When to Use

Use `create_plugin` when a user asks to:
- Build a new plugin for Evonic
- Add a new feature as a plugin (event hook, new page, API endpoint)
- Extend the platform with custom functionality

## Plugin Types

Choose `plugin_type` based on what the plugin needs to do:

| Type | Use When |
|---|---|
| `event_only` | Plugin reacts to agent events (e.g. send Slack notification on turn_complete) |
| `routes_only` | Plugin adds HTTP pages/API endpoints (e.g. a dashboard, a webhook receiver) |
| `full` | Plugin needs both event handlers AND HTTP routes |

## Available Events

| Event | Fires When |
|---|---|
| `turn_complete` | Agent finishes processing a conversation turn |
| `message_received` | A new message arrives (before processing) |
| `final_answer` | Agent produces its final response |
| `session_created` | A new session is created |
| `summary_updated` | The session summary is updated |
| `processing_started` | Agent starts processing |
| `llm_thinking` | LLM produces thinking/reasoning content |
| `llm_response_chunk` | LLM produces a response chunk |
| `tool_executed` | A tool call completes |
| `message_sent` | A message is sent via a channel |

Event handlers receive `(event: dict, sdk: PluginSDK)`.

### PluginSDK API

Inside event handlers:
- `sdk.send_message(agent_id, external_user_id, channel_id, text)` — send a message via a channel
- `sdk.http_request(method, url, json=..., timeout=15)` — HTTP calls to external services
- `sdk.get_session_messages(session_id, agent_id, limit)` — read conversation history
- `sdk.get_session(session_id)` — get session details
- `sdk.log(message, level)` — write to plugin logs (visible in /plugins UI)
- `sdk.config` — dict of plugin config values
- `sdk.event` — the event data dict

## Plugin Config Variables

Use `variables` when the plugin needs user-configurable settings (API keys, URLs, thresholds). These appear in the plugin's Settings tab in the UI.

Example:
```json
[
  {"name": "WEBHOOK_URL", "label": "Webhook URL", "type": "string", "default": "", "description": "Where to POST events"},
  {"name": "THRESHOLD", "label": "Threshold", "type": "number", "default": 5}
]
```

## Nav Items

Set `nav_label` to add the plugin to the main navigation bar. The label appears in the header alongside Dashboard, Agents, etc. Only use this for plugins that have a dedicated UI page.

## After Creating a Plugin

The plugin is hot-loaded immediately. Next steps:
1. Edit `plugins/<id>/handler.py` to implement event handler logic
2. Edit `plugins/<id>/routes.py` to implement API/page logic
3. Edit `plugins/<id>/templates/<id>.html` to customize the UI
4. Configure plugin variables at `/plugins` → select plugin → Settings

## Workflow

```
use_skill({id: "plugin_creator"})
→ create_plugin(id="...", ...)
→ [plugin is scaffolded and loaded]
→ unload_skill({id: "plugin_creator"})   # clean up context when done
```

## Rules

- Always call `unload_skill("plugin_creator")` after you are done creating plugins.
- Do not create a plugin if one with the same ID already exists — the tool will return an error.
- For `event_only` plugins, always specify the `events` array.
- For `routes_only` plugins, do NOT specify events (they are ignored).
- Keep `plugin_type` minimal — use `event_only` unless routes are explicitly needed.
