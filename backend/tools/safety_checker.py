"""
safety_checker — Heuristic safety checks for file system operation paths.

Blocks access to the .ssh/ directory to safeguard SSH private keys and
configurations from accidental or malicious exposure.

Usage:
    from backend.tools.safety_checker import check_ssh_path

    result = check_ssh_path("/home/user/.ssh/id_rsa")
    if result["blocked"]:
        return {"error": result["error"]}
"""

import os
import re

# Patterns that indicate a path targets the .ssh directory
_SSH_PATH_PATTERNS = [
    # Direct .ssh/ component anywhere in the path
    (re.compile(r"(?:^|/)\.ssh(?:/|$)"), "Path contains .ssh/ directory"),
    # Tilde-expanded .ssh
    (re.compile(r"^~[/\\]\.ssh(?:/|$)"), "Path references ~/.ssh/"),
    # /home/<user>/.ssh/
    (re.compile(r"^/home/[^/]+[/\\]\.ssh(?:/|$)"), "Path targets /home/<user>/.ssh/"),
    # /root/.ssh/
    (re.compile(r"^/root[/\\]\.ssh(?:/|$)"), "Path targets /root/.ssh/"),
    # Windows user .ssh
    (re.compile(r"^[A-Za-z]:\\Users\\[^\\]+\\\.ssh(?:\\|$)"), "Path targets Windows user .ssh/"),
    # SSH key files by name patterns (additional defense for bare key filenames)
    (re.compile(r"(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519|ecdsa-sk|ed25519-sk)(?:\.pub)?$"), "Path targets SSH private/public key file"),
]

# SSH key files — always-blocked even without .ssh directory context
_SSH_KEY_BARE_FILES = frozenset({
    "id_rsa", "id_rsa.pub", "id_dsa", "id_dsa.pub",
    "id_ecdsa", "id_ecdsa.pub", "id_ed25519", "id_ed25519.pub",
    "id_ecdsa-sk", "id_ecdsa-sk.pub", "id_ed25519-sk", "id_ed25519-sk.pub",
})

# SSH files only blocked when in .ssh directory context (checked by pattern + path component)
_SSH_CONTEXT_FILES = frozenset({
    "authorized_keys", "authorized_keys2", "known_hosts",
    "ssh_config", "config",
})


def _resolve_symlinks(path: str) -> str:
    """Resolve symlinks and normalize the path without following parent symlinks."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError, RuntimeError):
        return os.path.abspath(path)


def check_ssh_path(file_path: str, agent: dict = None) -> dict:
    """
    Check if a file path targets the .ssh/ directory or SSH key files.

    Uses multiple heuristics:
    1. Regex patterns against the raw path
    2. Path component analysis (splits path by separator)
    3. Canonical path resolution via realpath()

    Args:
        file_path: The file path to check (relative or absolute).
        agent: Optional agent context dict.

    Returns:
        {"blocked": bool, "error": str | None, "reason": str | None}
    """
    if not file_path or not isinstance(file_path, str):
        return {"blocked": False, "error": None, "reason": None}

    normalized = os.path.normpath(file_path.strip())

    # Layer 1: Regex pattern matching against the raw path
    for pattern, reason in _SSH_PATH_PATTERNS:
        if pattern.search(normalized):
            return {
                "blocked": True,
                "error": f"Safety check: Access to SSH directory denied. {reason}. The .ssh/ path is blocked to protect private keys and configurations.",
                "reason": reason,
            }

    # Layer 2: Path component analysis
    parts = normalized.replace("\\", "/").split("/")
    # Check if .ssh is a path component
    for i, part in enumerate(parts):
        if part == ".ssh":
            return {
                "blocked": True,
                "error": "Safety check: Access to SSH directory denied. Path contains .ssh/ directory component. The .ssh/ path is blocked to protect private keys and configurations.",
                "reason": "Path component analysis detected .ssh directory",
            }
        # Check SSH key file basenames — always block unmistakable key filenames
        if part in _SSH_KEY_BARE_FILES:
            return {
                "blocked": True,
                "error": f"Safety check: Access to SSH key file denied. '{part}' is an SSH private/key file. SSH keys are blocked to prevent exposure.",
                "reason": f"SSH key file detected: {part}",
            }

    # Layer 3: Canonical path resolution (resolves symlinks and '..')
    try:
        # Only attempt realpath if the path could plausibly exist
        # to avoid errors on purely synthetic paths
        if os.path.isabs(normalized) or normalized.startswith("~"):
            expanded = os.path.expanduser(normalized)
            if os.path.exists(expanded) or os.path.lexists(expanded):
                real = _resolve_symlinks(expanded)
                # Check resolved path
                for pattern, reason in _SSH_PATH_PATTERNS:
                    if pattern.search(real):
                        return {
                            "blocked": True,
                            "error": f"Safety check: Access to SSH directory denied. Canonical path resolves to .ssh/ directory. The .ssh/ path is blocked to protect private keys and configurations.",
                            "reason": f"Canonical path check: {reason}",
                        }
                # Check components of resolved path
                rparts = real.replace("\\", "/").split("/")
                for part in rparts:
                    if part == ".ssh":
                        return {
                            "blocked": True,
                            "error": "Safety check: Access to SSH directory denied. Canonical path contains .ssh/ component. The .ssh/ path is blocked to protect private keys and configurations.",
                            "reason": "Canonical path component analysis detected .ssh directory",
                        }
    except (OSError, ValueError, RuntimeError):
        pass

    return {"blocked": False, "error": None, "reason": None}


# ---------------------------------------------------------------------------
# SQLite Database File Check
# ---------------------------------------------------------------------------

# SQLite database file extensions
_SQLITE_EXTENSIONS = frozenset({'.db', '.sqlite', '.sqlite3'})

# Known sensitive database filenames (higher priority)
_SENSITIVE_DB_FILES = frozenset({
    'chat.db',       # Project chat/database
    'database.db',   # Generic but obviously a database
})


def check_sqlite_path(file_path: str, agent: dict = None) -> dict:
    """
    Check if a file path targets an SQLite database file.

    Uses multiple heuristics:
    1. File extension matching (.db, .sqlite, .sqlite3)
    2. Known sensitive database filenames
    3. Path component analysis

    Args:
        file_path: The file path to check (relative or absolute).
        agent: Optional agent context dict (for future super-agent exemption).

    Returns:
        {"blocked": bool, "error": str | None, "reason": str | None,
         "requires_approval": bool}
    """
    if not file_path or not isinstance(file_path, str):
        return {"blocked": False, "error": None, "reason": None, "requires_approval": False}

    normalized = os.path.normpath(file_path.strip())

    # Layer 1: Check extension
    _, ext = os.path.splitext(normalized)
    ext_lower = ext.lower()

    if ext_lower in _SQLITE_EXTENSIONS:
        basename = os.path.basename(normalized)
        if basename in _SENSITIVE_DB_FILES:
            return {
                "blocked": True,
                "error": f"Safety check: Access to SQLite database denied. '{basename}' is a sensitive project database. Database file access requires approval.",
                "reason": f"Sensitive database file detected: {basename}",
                "requires_approval": True,
            }
        return {
            "blocked": True,
            "error": f"Safety check: Access to SQLite database file denied. '{basename}' is a database file ({ext_lower}). Database access requires approval.",
            "reason": f"SQLite database file detected: {basename}",
            "requires_approval": True,
        }

    # Layer 2: Path component analysis
    parts = normalized.replace("\\", "/").split("/")
    for part in parts:
        _, part_ext = os.path.splitext(part)
        if part_ext.lower() in _SQLITE_EXTENSIONS:
            if part in _SENSITIVE_DB_FILES:
                return {
                    "blocked": True,
                    "error": f"Safety check: Access to SQLite database denied. Path references '{part}', a sensitive project database. Database file access requires approval.",
                    "reason": f"Sensitive database file in path: {part}",
                    "requires_approval": True,
                }
            return {
                "blocked": True,
                "error": f"Safety check: Access to SQLite database file denied. Path references '{part}', a database file. Database access requires approval.",
                "reason": f"Database file in path: {part}",
                "requires_approval": True,
            }

    # Layer 3: Canonical path resolution
    try:
        if os.path.isabs(normalized) or normalized.startswith("~"):
            expanded = os.path.expanduser(normalized)
            if os.path.exists(expanded) or os.path.lexists(expanded):
                real = os.path.realpath(expanded)
                _, real_ext = os.path.splitext(real)
                if real_ext.lower() in _SQLITE_EXTENSIONS:
                    basename = os.path.basename(real)
                    return {
                        "blocked": True,
                        "error": f"Safety check: Access to SQLite database denied. Canonical path resolves to '{basename}', a database file. Database access requires approval.",
                        "reason": f"Canonical path resolves to database file: {basename}",
                        "requires_approval": True,
                    }
    except (OSError, ValueError, RuntimeError):
        pass

    return {"blocked": False, "error": None, "reason": None, "requires_approval": False}
