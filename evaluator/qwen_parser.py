"""
Qwen Tool Call Parser

Handles Qwen's native XML tool call format that sometimes appears when the model
falls back from OpenAI-compatible function calling:

    <tool_call>
    <function=tool_name>
    <parameter=param_name>value</parameter>
    <parameter=param2_name>multiline
    value here</parameter>
    </function>
    </tool_call>

Multiple tool calls may appear in a single response.
"""

import re
import json
import uuid
from typing import Dict, Any, Optional, List, Tuple


def is_qwen_format(text: str) -> bool:
    """Return True if text contains Qwen-style <tool_call> XML."""
    return bool(text and '<tool_call>' in text)


def extract_qwen_tool_calls(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extract tool calls from Qwen XML format.

    Supports:
    - Single and multiple <tool_call> blocks
    - Multiline parameter values (e.g. code blocks)
    - Optional whitespace around tags

    Args:
        text: Raw LLM response content

    Returns:
        List of {'name': str, 'arguments': dict} dicts, or None if none found.
    """
    if not text or '<tool_call>' not in text:
        return None

    tool_calls = []

    # Extract each <tool_call>...</tool_call> block
    block_pattern = re.compile(r'<tool_call>(.*?)</tool_call>', re.DOTALL)
    for block_match in block_pattern.finditer(text):
        block = block_match.group(1)

        # Extract function name from <function=NAME>
        func_match = re.search(r'<function=([^>]+)>', block)
        if not func_match:
            continue
        func_name = func_match.group(1).strip()

        # Extract parameters from <parameter=NAME>VALUE</parameter>
        # Value may be multiline
        param_pattern = re.compile(r'<parameter=([^>]+)>(.*?)</parameter>', re.DOTALL)
        arguments = {}
        for param_match in param_pattern.finditer(block):
            param_name = param_match.group(1).strip()
            param_value = param_match.group(2)
            # Strip exactly one leading/trailing newline to preserve indentation in code blocks
            if param_value.startswith('\n'):
                param_value = param_value[1:]
            if param_value.endswith('\n'):
                param_value = param_value[:-1]
            arguments[param_name] = param_value

        tool_calls.append({
            "name": func_name,
            "arguments": arguments,
        })

    return tool_calls if tool_calls else None


def qwen_tool_calls_to_openai_format(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert parsed Qwen tool calls to OpenAI-compatible tool_calls format.

    Args:
        tool_calls: List of {'name': str, 'arguments': dict}

    Returns:
        List in OpenAI tool_calls format with id, type, function.name, function.arguments
    """
    if not tool_calls:
        return []

    result = []
    for tc in tool_calls:
        result.append({
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(tc["arguments"]),
            },
        })
    return result


def strip_qwen_tool_calls(text: str) -> str:
    """
    Remove all <tool_call>...</tool_call> blocks from text,
    returning the remaining visible content (trimmed).

    Args:
        text: Raw LLM response content

    Returns:
        Content with tool call XML removed
    """
    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    return cleaned.strip()
