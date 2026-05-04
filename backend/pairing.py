"""Pairing code generation and validation.

Generates 6-character alphanumeric codes (A-Z, 0-9) displayed as XXX-XXX.
"""

import random
import re
import string

_CHARS = string.ascii_uppercase + string.digits
_CODE_LEN = 6
_SEGMENT_LEN = 3
# Format: XXX-XXX (7 chars including hyphen)
_PATTERN = re.compile(r'^[A-Z0-9]{3}-[A-Z0-9]{3}$')

# Extracts a 6-char pairing code from arbitrary text.
# Matches: ABC-123, ABC123, "my code is ABC-123 thanks" -> "ABC123"
# Group 1 = first 3 chars, Group 2 = last 3 chars (never joined by a hyphen in group 0)
_EXTRACT_RE = re.compile(r'(?:^|[^A-Z0-9])([A-Z0-9]{3})-?([A-Z0-9]{3})(?:[^A-Z0-9]|$)')


def generate_pair_code() -> str:
    """Generate a 6-char alphanumeric pairing code (raw, no hyphen)."""
    return ''.join(random.choices(_CHARS, k=_CODE_LEN))


def format_pair_code(raw: str) -> str:
    """Format a 6-char raw code as XXX-XXX."""
    return f"{raw[:_SEGMENT_LEN]}-{raw[_SEGMENT_LEN:]}"


def validate_pair_code(code: str | None) -> bool:
    """Check if a string matches the XXX-XXX pattern (uppercase A-Z, 0-9)."""
    return bool(code is not None and _PATTERN.match(code))


def extract_pair_code(text: str | None) -> str | None:
    """Extract a 6-char alphanumeric pairing code from arbitrary text.

    Accepts codes with or without hyphen (e.g. 'ABC-123' or 'ABC123'),
    and codes embedded in surrounding text (e.g. 'my code is ABC-123 thanks').

    Returns the raw 6-char code (uppercase, no hyphen) or None if no valid
    code is found.
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip().upper()
    # Try exact match first (the whole message is a bare code)
    if len(text) == 6 and all(c in _CHARS for c in text):
        return text
    if len(text) == 7 and text[3] == '-' and all(c in _CHARS for c in text[:3] + text[4:]):
        return text[:3] + text[4:]
    # Search for pattern in text: 3 alnum + optional hyphen + 3 alnum, bounded by non-alnum or edges
    m = _EXTRACT_RE.search(text)
    if m:
        return m.group(1) + m.group(2)
    return None
