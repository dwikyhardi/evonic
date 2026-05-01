"""
llm_tool_executor.py — tool execution constants.

Part of the diet llm_loop.py refactor (Layout C / Pipeline).
"""

# Hard cap on how many times an injection may reset the iteration counter
# within a single loop run. Without this, continuous injections (e.g. autopilot
# kanban) could keep resetting _iteration forever — infinite loop.
MAX_INJECTIONS_PER_LOOP = 5
