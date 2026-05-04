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


def generate_pair_code() -> str:
    """Generate a 6-char alphanumeric pairing code (raw, no hyphen)."""
    return ''.join(random.choices(_CHARS, k=_CODE_LEN))


def format_pair_code(raw: str) -> str:
    """Format a 6-char raw code as XXX-XXX."""
    return f"{raw[:_SEGMENT_LEN]}-{raw[_SEGMENT_LEN:]}"


def validate_pair_code(code: str) -> bool:
    """Check if a string matches the XXX-XXX pattern (uppercase A-Z, 0-9)."""
    return bool(_PATTERN.match(code))
