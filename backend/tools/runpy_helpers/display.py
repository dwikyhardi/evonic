"""
evonic.display — structured output formatting for agentic workflows.

All functions print to stdout and also return the formatted string.
"""

import difflib
import json as _json
import os


def json(obj, indent: int = 2) -> str:
    """Pretty-print a Python object as JSON.

    Args:
        obj:    Any JSON-serialisable object.
        indent: Indentation spaces (default: 2).

    Returns:
        JSON string (also printed to stdout).
    """
    result = _json.dumps(obj, indent=indent, ensure_ascii=False, default=str)
    print(result)
    return result


def diff(a, b, label_a: str = 'a', label_b: str = 'b') -> str:
    """Show a unified diff between two strings or file paths.

    Args:
        a, b:    Either strings of content or file paths (auto-detected).
        label_a: Label for the 'before' side (default: 'a').
        label_b: Label for the 'after' side (default: 'b').

    Returns:
        Unified diff string (also printed to stdout).
    """
    def _load(x, label):
        if isinstance(x, str) and os.path.isfile(x):
            with open(x, errors='replace') as f:
                return f.readlines(), x
        return x.splitlines(keepends=True), label

    lines_a, from_label = _load(a, label_a)
    lines_b, to_label = _load(b, label_b)

    result = ''.join(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=from_label, tofile=to_label,
    ))
    if not result:
        result = '(no differences)'
    print(result)
    return result


def truncate(text: str, max_lines: int = 50) -> str:
    """Show a head/tail preview of long text.

    If the text has more than max_lines lines, shows the first and last
    max_lines//2 lines with a summary in between.

    Args:
        text:      Input text.
        max_lines: Maximum lines before truncation kicks in (default: 50).

    Returns:
        Possibly-truncated string (also printed to stdout).
    """
    lines = text.splitlines()
    total = len(lines)
    if total <= max_lines:
        print(text)
        return text

    half = max_lines // 2
    head = lines[:half]
    tail = lines[total - half:]
    hidden = total - max_lines
    result = '\n'.join(head) + f'\n... ({hidden} lines hidden) ...\n' + '\n'.join(tail)
    print(result)
    return result
