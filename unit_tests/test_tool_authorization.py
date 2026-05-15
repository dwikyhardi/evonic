"""
Unit tests for the ToolRegistry authorization guard.

Tests that get_real_executor() correctly validates the assigned_tool_ids
before allowing execution, and blocks unassigned tools.
"""

import os
import sys
import pytest

from backend.tools.registry import ToolRegistry


class TestToolAuthorization:
    """Tests for the authorization guard in ToolRegistry.get_real_executor()."""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    # ------------------------------------------------------------------
    # Helper to build a minimal agent_context dict for testing
    # ------------------------------------------------------------------
    def _context(self, tool_ids: list, agent_id: str = "test-agent") -> dict:
        return {
            "agent_id": agent_id,
            "assigned_tool_ids": list(tool_ids),
            "is_super": False,
            "session_id": "test-session",
        }

    # ------------------------------------------------------------------
    # Blocked tests (tool NOT in assigned_tool_ids)
    # ------------------------------------------------------------------

    def test_blocks_unassigned_tool(self, registry):
        """A tool not in assigned_tool_ids must be blocked."""
        ctx = self._context(["bash", "write_file"])
        executor = registry.get_real_executor(ctx)
        result = executor("read_file", {})
        assert result.get("blocked_by") == "authorization"
        assert "not assigned" in result.get("error", "").lower()

    def test_blocks_skill_tool_without_namespace(self, registry):
        """A skill tool (icd10_search) without any namespace in assigned_tool_ids is blocked."""
        ctx = self._context(["bash", "write_file", "read_file"])
        executor = registry.get_real_executor(ctx)
        result = executor("icd10_search", {"query": "diabetes"})
        assert result.get("blocked_by") == "authorization"
        assert "not assigned" in result.get("error", "").lower()

    def test_blocks_unknown_tool(self, registry):
        """A completely unknown tool name must be blocked."""
        ctx = self._context(["bash"])
        executor = registry.get_real_executor(ctx)
        result = executor("nonexistent_tool_xyz", {})
        assert result.get("blocked_by") == "authorization"

    def test_blocks_empty_assignment(self, registry):
        """When assigned_tool_ids is empty, every tool should be blocked."""
        ctx = self._context([])
        executor = registry.get_real_executor(ctx)
        result = executor("bash", {"script": "echo hi"})
        assert result.get("blocked_by") == "authorization"

    # ------------------------------------------------------------------
    # Allowed tests (tool IS in assigned_tool_ids)
    # ------------------------------------------------------------------

    def test_allows_exact_match(self, registry):
        """A tool that matches exactly by bare name is allowed.

        Note: the executor will try to load the actual backend, so we
        expect a 'module not found' error (not a blocked_by), proving
        the authorization guard passed.
        """
        ctx = self._context(["bash"])
        executor = registry.get_real_executor(ctx)
        result = executor("bash", {"script": "echo hi"})
        # If authorization guard passes, it will try to execute and
        # either succeed or return an execution error -- but NOT blocked_by
        assert result.get("blocked_by") != "authorization"

    def test_allows_namepaced_skill_tool(self, registry):
        """A skill tool referenced via namespaced ID (skill:*:fn) must be allowed."""
        ctx = self._context([
            "bash",
            "skill:claimguard:icd10_search",
            "skill:claimguard:icd10_search2",
        ])
        executor = registry.get_real_executor(ctx)
        result = executor("icd10_search", {"query": "diabetes"})
        # Some tool backends return a string directly on success, others return a dict.
        # If it was blocked, result will be a dict with 'blocked_by'.
        if isinstance(result, dict):
            assert result.get("blocked_by") != "authorization", (
                f"Tool was blocked: {result.get('error')}"
            )
        # If it's a string (tool executed successfully), that's fine too.

    def test_allows_all_assigned_tools(self, registry):
        """All tools listed in assigned_tool_ids must pass the guard."""
        ctx = self._context(["bash", "read_file", "write_file", "str_replace", "patch"])
        executor = registry.get_real_executor(ctx)
        for tool in ["bash", "read_file", "write_file", "str_replace", "patch"]:
            result = executor(tool, {} if tool == "bash" else {"file_path": "/tmp/test"})
            if isinstance(result, dict):
                assert result.get("blocked_by") != "authorization", (
                    f"Tool '{tool}' was blocked but should be allowed"
                )
            # Non-dict results (e.g. strings from built-in tools) are fine

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_super_agent_can_call_anything(self, registry):
        """Super agent (is_super=True) may bypass -- depending on implementation.

        Currently the guard checks assigned_tool_ids regardless of is_super.
        If that changes, this test documents the expected behavior.
        """
        ctx = self._context(["bash"], agent_id="super")
        ctx["is_super"] = True
        executor = registry.get_real_executor(ctx)
        result = executor("unassigned_tool", {})
        # Currently super agent still needs tools assigned, so this is blocked
        # If super bypass is added, update this test.
        assert result.get("blocked_by") == "authorization"

    def test_missing_assigned_tool_ids_key(self, registry):
        """When assigned_tool_ids key is missing, assume empty list (block all)."""
        ctx = {"agent_id": "test", "is_super": False}
        executor = registry.get_real_executor(ctx)
        result = executor("bash", {})
        assert result.get("blocked_by") == "authorization"

    def test_tool_id_with_trailing_namespace(self, registry):
        """A tool whose ID ends with the function name via colon should match."""
        ctx = self._context(["skill:myplugin:custom_tool"])
        executor = registry.get_real_executor(ctx)
        result = executor("custom_tool", {})
        # Should pass authorization (matched via endswith check) and then
        # attempt execution. If blocked, result will be a dict with 'blocked_by'.
        if isinstance(result, dict):
            assert result.get("blocked_by") != "authorization"
