# Evonic

> **Swarm Intelligence, Zero Lock-in.**
> *Your Models. Your Rules. Your Swarm.*

Evonic is an agentic AI platform for building, managing, and orchestrating AI agents. Designed for open models, it supports multi-agent swarms, modular skills, and seamless deployment across channels — all without vendor lock-in.

**Full documentation:** [evonic.dev](https://evonic.dev)

---

## Key Features

- **Agents** — Independent, LLM-powered assistants with tools, knowledge bases, and isolated workspaces
- **Skills** — Installable packages that bundle tool definitions with Python backends
- **Plugins** — Event-driven extensions for custom integrations and background workers
- **Workplaces** — Execution environments: local, SSH servers, or cloud devices via Evonet
- **Evonet** — Lightweight connector that enables remote execution without SSH or firewall rules
- **Scheduler** — Schedule recurring tasks, reminders, and cron-based triggers for agents
- **Channels** — Connect agents to Telegram, WhatsApp, Discord, and more
- **Evaluation Engine** — Test and benchmark LLM capabilities with customizable evaluators
- **Safety by Design** — Sandboxed execution + heuristic safety system for agent actions

---

## Getting Started

### Prerequisites

- **Python 3.8+**
- **LLM endpoint** — OpenAI-compatible API (local or cloud)

### Installation

```bash
git clone https://github.com/anvie/evonic
cd evonic
pip install -r requirements.txt
chmod +x ./evonic
```

### Start

```bash
./evonic start
```

Open `http://localhost:8080` in your browser.

### Docker Sandbox (optional)

Agent tools like `bash` and `runpy` run inside an isolated Docker container by default:

```bash
docker build -t evonic-sandbox:latest docker/tools/
```

Configure resource limits in `.env` (memory, CPU, network). If Docker is unavailable, set `sandbox_enabled=0` to fall back to local execution.

---

## Agents

Create and manage agents via the web UI (`/agents`) or CLI:

```bash
./evonic agent add my_bot --name "My Bot"
./evonic agent add dev_bot --name "Dev Bot" --skillset coder
./evonic agent enable my_bot
./evonic agent remove my_bot
```

Each agent has its own system prompt, assigned tools, knowledge base, and workspace.

---

## Skills

Skills extend agents with new capabilities. Install via CLI:

```bash
./evonic skill install path/to/skill.zip
./evonic skill list
./evonic skill enable math
./evonic skill uninstall math
```

Skills follow a load → context → execute lifecycle, keeping the agent's system prompt lean and modular.

---

## Plugins

Plugins are event-driven extensions that hook into the platform's event stream. Manage them via CLI:

```bash
./evonic plugin install path/to/plugin.zip
./evonic plugin list
./evonic plugin uninstall my_plugin
```

---

## Models

Manage LLM configurations:

```bash
./evonic model add gpt4o --name "GPT-4o" --provider openai --api-key "sk-..." --base-url "https://api.openai.com/v1"
./evonic model list
./evonic model rm gpt4o
```

---

[] Robin Syihab
