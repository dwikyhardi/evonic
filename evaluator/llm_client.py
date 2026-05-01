# Compatibility shim — LLMClient has moved to backend/llm_client.py.
# All evaluator/* files import from here and continue to work unchanged.
from backend.llm_client import LLMClient, llm_client, strip_thinking_tags  # noqa: F401
