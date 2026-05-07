"""
safety_base — Abstract base class and shared types for safety checkers.

All safety checkers (built-in heuristic, custom regex rules, user code checkers)
implement SafetyCheckerBase so the SafetyPipeline can orchestrate them uniformly.
"""

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class MatchedPattern(TypedDict, total=False):
    """A single pattern match returned by a checker."""
    pattern: str
    weight: int
    category: str
    description: str


class CheckResult(TypedDict, total=False):
    """Result returned by each checker in the pipeline.

    The pipeline aggregates these across all checkers, then applies
    threshold logic to determine the final level.
    """
    score: int
    reasons: list[str]
    matched_patterns: list[MatchedPattern]
    blocked_patterns: list[str]


class SafetyCheckerBase(ABC):
    """Interface that every safety checker must implement."""

    @abstractmethod
    def check(self, code: str, tool_type: str, agent_context: dict[str, Any] | None = None) -> CheckResult:
        """
        Analyse *code* and return a partial result (score + reasons).

        Args:
            code: Source code or shell script to inspect.
            tool_type: ``'python'`` or ``'bash'``.
            agent_context: Runtime agent dict (contains agent_id, etc.).
                           May be ``None`` when called from tests or outside
                           an agent execution context.

        Returns:
            A :class:`CheckResult` dict.  The caller (SafetyPipeline) merges
            results from all checkers and decides the final safety level.
        """
        ...
