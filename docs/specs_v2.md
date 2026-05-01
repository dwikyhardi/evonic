Feature Request: Agentic Platform with Modular Channel Integration
I want to evolve this program beyond a simple LLM evaluator into a full agentic platform — capable of both evaluation workflows and production serving. In production mode, every user request will be routed through this system as a proxy, with per-user session persistence across conversations.

Channel Integration — Modular & Abstracted
The platform should support multiple chat channels (Telegram, WhatsApp, Discord, etc.), but we’ll start with Telegram as the first integration. The architecture must be fully modular, built on a clean abstraction layer so that adding new channels in the future requires minimal effort — just implementing the interface, not restructuring the core.

New Page: /agents — Agent Management
Add a dedicated Agent Management section at /agents with full CRUD capabilities:
	∙	List all agents
	∙	Create a new agent
	∙	Edit an existing agent
	∙	Delete an agent
Each agent has a unique slug-format ID — alphanumeric and underscores only, no spaces or special characters (e.g., example_agent, office_hrd). The individual agent settings page lives at /agents/[id].

Per-Agent Configuration (/agents/[id])
Each agent should be independently configurable with:
	∙	System Prompt — define the agent’s persona and behavior
	∙	Knowledge Files — attach .md files as supplementary knowledge/context
	∙	Function Tools — assign tools from the existing tool registry (currently used in test evals)
	∙	Channel Pairing — connect the agent to one or more channels (e.g., Telegram, WhatsApp) via the channel abstraction layer

Tool System Refactor — Unified Signature for Eval & Production
Currently, tools are used exclusively in test evaluations (with mock implementations). We need to refactor the tool mechanism so that:
	1.	Tool signatures are unified — the same tool definition works in both eval and production contexts
	2.	In eval mode → tools call mock/simulated functions
	3.	In production mode → tools call real backend implementations
This requires building real backend tool implementations in Python, housed in a dedicated directory (e.g., /backend/tools/). Each tool’s backend function must match the signature expected by the LLM, ensuring seamless compatibility whether invoked during testing or live production serving. The backend tools code must auto-reload when code inside /tools dir changed.
