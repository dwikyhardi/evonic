"""
Task Complexity Classifier — determines if a task is trivial or complex.

Trivial tasks start in "execute" mode (writes allowed immediately).
Complex tasks start in "plan" mode (must plan before writing).

Uses a lightweight LLM call (no tools, no thinking) with an optional
heuristic fast-path to skip the LLM entirely for obvious cases.
"""

import logging
import re
from typing import Optional

import config
from backend.llm_client import LLMClient

_logger = logging.getLogger(__name__)

# Heuristic thresholds
_TRIVIAL_MAX_WORDS = 15
_COMPLEX_MIN_WORDS = 80

# Keywords that strongly suggest complexity
_COMPLEX_KEYWORDS = {
    "refactor", "redesign", "migrate", "architect", "implement",
    "integrate", "optimize", "review", "analyze", "investigate",
    "debug", "troubleshoot", "upgrade", "overhaul", "restructure",
    "design", "plan", "strategy", "multiple", "several", "across",
}

# Patterns that suggest trivial single-action tasks
_TRIVIAL_PATTERNS = [
    re.compile(r"^(create|write|make|add|generate)\s+(a\s+)?(\w+\s+){0,3}file", re.I),
    re.compile(r"^(say|print|echo|output)\s+", re.I),
    re.compile(r"^(create|write)\s+hello\s+world", re.I),
]

_CLASSIFIER_SYSTEM = """You classify tasks as TRIVIAL or COMPLEX for an AI coding agent.

TRIVIAL: Can be completed in 1-2 file operations with no ambiguity. Examples:
- "Create a hello world Python file"
- "Add a .gitignore file"
- "Write a simple README"
- "Create an empty index.html"

COMPLEX: Requires research, reading existing code, multi-step changes, or design decisions. Examples:
- "Add authentication to the API"
- "Fix the bug in the payment module"
- "Refactor the database layer"
- "Create a REST API with CRUD operations"
- Any task mentioning existing code/files that need to be understood first

When in doubt, classify as COMPLEX.
Respond with exactly one word: TRIVIAL or COMPLEX"""


def _get_classifier_client() -> LLMClient:
    """Build an LLMClient for classification, using the configured model or default."""
    try:
        from models.db import db
        model_id = db.get_setting('task_classifier_model_id', '')
        if model_id:
            model = db.get_model_by_id(model_id)
            if model:
                return LLMClient(model_config=model)
            _logger.warning("Classifier model_id '%s' not found, falling back to default", model_id)
    except Exception as e:
        _logger.warning("Could not load classifier model config: %s", e)
    return LLMClient()


def _is_enabled() -> bool:
    """Check if the task classifier is enabled (DB setting overrides config default)."""
    try:
        from models.db import db
        default = '1' if config.TASK_CLASSIFIER_ENABLED else '0'
        return db.get_setting('task_classifier_enabled', default) == '1'
    except Exception:
        return config.TASK_CLASSIFIER_ENABLED


def _heuristic_classify(text: str) -> Optional[str]:
    """Fast-path heuristic. Returns 'trivial', 'complex', or None (needs LLM)."""
    words = text.split()
    word_count = len(words)

    # Very short + matches a trivial pattern -> trivial
    if word_count <= _TRIVIAL_MAX_WORDS:
        for pat in _TRIVIAL_PATTERNS:
            if pat.search(text):
                return "trivial"

    # Long message or contains complexity keywords -> complex
    if word_count >= _COMPLEX_MIN_WORDS:
        return "complex"
    lower_words = set(text.lower().split())
    if lower_words & _COMPLEX_KEYWORDS:
        return "complex"

    return None  # uncertain, need LLM


def classify_task(user_message: str) -> str:
    """Classify a task as 'trivial' or 'complex'.

    Returns 'trivial' or 'complex'. Defaults to 'complex' on any error.
    """
    if not _is_enabled():
        return "complex"

    text = user_message.strip()
    if not text:
        return "complex"

    # Try heuristic first
    result = _heuristic_classify(text)
    if result:
        _logger.info("Task classified as %s (heuristic)", result)
        return result

    # LLM classification
    try:
        client = _get_classifier_client()
        messages = [
            {"role": "system", "content": _CLASSIFIER_SYSTEM},
            {"role": "user", "content": text},
        ]
        response = client.chat_completion(
            messages,
            tools=None,
            temperature=0.0,
            enable_thinking=False,
            max_tokens=10,
        )
        if not response.get("success"):
            _logger.warning("Task classifier LLM call failed: %s", response.get("error_type"))
            return "complex"
        choices = response.get("response", {}).get("choices", [])
        if not choices:
            return "complex"
        content = choices[0].get("message", {}).get("content", "").strip().upper()
        if "TRIVIAL" in content:
            _logger.info("Task classified as trivial (LLM)")
            return "trivial"
        _logger.info("Task classified as complex (LLM: %s)", content[:20])
        return "complex"
    except Exception as e:
        _logger.warning("Task classifier failed, defaulting to complex: %s", e)
        return "complex"
