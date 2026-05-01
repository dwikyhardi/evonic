# Evonic Platform Knowledge

This document explains how the Evonic agent platform works internally. Use this knowledge whenever you need to understand or modify the platform itself.

## Architecture Overview

Evonic is an agent orchestration platform. Here is how the key pieces fit together:

### Directory Structure

All agent data lives under the `agents/` directory at the project root. Each agent gets its own subdirectory:

```
agents/
  <agent_id>/
    SYSTEM.md    — the agent's system prompt (rules, persona, workflow)
    kb/          — knowledge base files the agent can read with the `read` tool
    chat.db      — per-agent SQLite database (chat history, memory, summaries)
    sessions/    — JSONL chat logs for streaming/SSE (used by chatlog_manager)
```

The super agent (first agent created during setup) additionally has access to tools for managing other agents.

### System Prompt

Every agent's system prompt lives in `agents/<agent_id>/SYSTEM.md`. This file is:

- Written once during agent creation (via `create_agent` or `apply_skillset`)
- Can be updated later with the `update_agent` tool
- Loaded at the start of every conversation turn and injected as the system message
- Also stored in the DB (`agents` table, `system_prompt` column)

The super agent's default system prompt lives in `defaults/super_agent_system_prompt.md` and is used as the base template during first-time setup.

### Key Backend Components

- `backend/agent_runtime/runtime.py` — main orchestrator: message queue, worker threads, session lifecycle
- `backend/agent_runtime/llm_loop.py` — the LLM interaction loop (tool calling, response handling)
- `backend/agent_runtime/context.py` — builds the system prompt + tool definitions for each turn
- `backend/agent_runtime/summarizer.py` — conversation summarization and context management
- `backend/agent_runtime/memory_manager.py` — long-term memory extraction and retrieval
- `backend/tools/` — all tool implementations (bash, read_file, write_file, patch, etc.)
- `backend/tools/registry.py` — tool registry; defines built-in tools and their factories
- `backend/channels/` — channel adapters (Telegram, etc.)
- `plugins/` — installable skills (kanban, scheduler, plugin_creator, etc.)
- `models/db.py` — database layer (SQLite per agent)

### Agent State

Agents have a `set_mode` tool that controls their working mode:
- **plan mode** — write tools (write_file, patch, str_replace) are BLOCKED; agent can only read and plan
- **execute mode** — all tools available; agent can write code and make changes

State handlers (kanban, etc.) are registered via `backend/plugin_manager.py` and managed through the `state` tool using `namespace:action` labels (e.g. `kanban:pick`, `kanban:finish`).

---

## Knowledge Base (KB)

### What It Is

Each agent has a `kb/` directory under `agents/<agent_id>/kb/`. This directory holds markdown or text files that the agent can read at any time using the built-in `read` tool.

### How to Use the `read` Tool

The `read` tool is specifically for KB files. You call it with a bare filename only:

```
read(filename="architecture.md")
```

Rules:
- Only bare filenames — no slashes, no paths (e.g. use "notes.md", NOT "/kb/notes.md")
- The tool is sandboxed to only read from your own `kb/` directory
- To read source code, logs, or workspace files, use the `read_file` tool instead

### Managing KB Files

The super agent can create and update KB files using `write_file` and `read_file`:
- `write_file` — create or overwrite files in `agents/<agent_id>/kb/`
- `read_file` — read any file including KB files (supports pagination for large files)

### When to Use KB

KB is ideal for:
- Platform documentation (like this file!)
- Reference material that should persist across conversations
- Pre-loaded knowledge about the agent's role and environment
- Static data the agent needs to consult regularly

KB is NOT for:
- Dynamic conversation state (use the memory system instead)
- User-specific facts that change (use `remember` / `recall`)
- Temporary working data

---

## Built-in Memory System

### What It Does

The memory system stores durable facts about users across conversations. It follows an Extract → Deduplicate → Store → Retrieve pipeline:

1. **Extract** — after conversation summarization, an LLM extracts salient facts (names, preferences, decisions, context)
2. **Deduplicate** — new facts are compared against existing memories; duplicates are skipped, contradictions trigger updates
3. **Store** — memories are persisted in the per-agent SQLite DB (FTS5 indexed for fast keyword search)
4. **Retrieve** — at the start of each turn, relevant memories are retrieved using the user's latest message as a search query and injected into the LLM context

### Tools

- **`remember`** — explicitly store a fact. Use this when the user shares important info.
  - `content`: the fact as a single clear sentence
  - `category`: one of `user_info`, `preference`, `decision`, `context`, `instruction`, `general`

- **`recall`** — search stored memories by keywords.
  - `query`: keywords to search for (uses FTS5 full-text search)

### Memory Categories

| Category     | Purpose                                          |
|-------------|--------------------------------------------------|
| user_info   | Identity, contact info (name, phone, email)      |
| preference  | Likes/dislikes, communication style, language    |
| decision    | Commitments or choices made by the user          |
| context     | Background about the user's project or situation |
| instruction | Persistent behavioral instructions               |
| general     | Anything else worth remembering                  |

### When to Use

- User shares their name, phone, or email → `remember(category="user_info")`
- User states a preference ("I prefer short answers") → `remember(category="preference")`
- User gives persistent instructions ("Always use English") → `remember(category="instruction")`
- User mentions project context → `remember(category="context")`
- Before responding in a new conversation, always check with `recall` if there are relevant memories
