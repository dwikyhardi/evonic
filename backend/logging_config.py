"""
Centralized logging configuration for Evonic.

Usage:
    # At startup (app.py, supervisor.py, cli):
    from backend.logging_config import configure
    configure()

    # In any module:
    from backend.logging_config import get_logger
    log = get_logger(__name__)
    log.info("message")

Format: [LEVEL] [module.path] message

Environment variables:
    EVONIC_LOG_LEVEL     — default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    EVONIC_LOG_FILE      — path to log file (default: logs/evonic.log); empty = disable file
    EVONIC_LOG_MAX_BYTES — max log file size before rotation (default: 5 MB)
    EVONIC_LOG_BACKUPS   — number of rotated backup files to keep (default: 3)
    EVONIC_LOG_QUIET     — comma-separated list of module names to silence (default: WARNING level)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

# ── Defaults ────────────────────────────────────────────────────────────────

_LOG_FORMAT = "[%(levelname)s] [%(name)s] %(message)s"
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "evonic.log"
)
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_DEFAULT_BACKUPS = 3

_configured = False


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(_LOG_FORMAT)


def configure(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backups: Optional[int] = None,
    console: bool = True,
) -> None:
    """Configure root logger once at application startup.

    Args:
        level: Log level string, read from EVONIC_LOG_LEVEL if None.
        log_file: Path to rotating log file, read from EVONIC_LOG_FILE if None.
            Pass empty string to disable file output.
        max_bytes: Max size before rotation, read from EVONIC_LOG_MAX_BYTES if None.
        backups: Number of backup files, read from EVONIC_LOG_BACKUPS if None.
        console: Whether to attach a StreamHandler to stdout.
    """
    global _configured
    if _configured:
        return  # idempotent — safe to call multiple times

    # Resolve env vars / defaults
    level = level or os.environ.get("EVONIC_LOG_LEVEL", _DEFAULT_LOG_LEVEL).upper()
    log_file = log_file if log_file is not None else os.environ.get("EVONIC_LOG_FILE", _DEFAULT_LOG_FILE)
    max_bytes = max_bytes or int(os.environ.get("EVONIC_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES))
    backups = backups if backups is not None else int(os.environ.get("EVONIC_LOG_BACKUPS", _DEFAULT_BACKUPS))
    # Bounds check
    if max_bytes < 1:
        max_bytes = _DEFAULT_MAX_BYTES
    if max_bytes > 1_073_741_824:  # 1 GiB
        max_bytes = 1_073_741_824
    if backups is not None and (backups < 1 or backups > 100):
        backups = _DEFAULT_BACKUPS

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    # Silence noisy third-party modules
    quiet = os.environ.get("EVONIC_LOG_QUIET", "").split(",")
    for name in quiet:
        name = name.strip()
        if name:
            logging.getLogger(name).setLevel(logging.ERROR)

    formatter = _build_formatter()

    # Console handler (stdout)
    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    # File handler with rotation
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, automatically configured on first call.

    If logging has not been configured yet, configure() is called with defaults.
    This ensures modules get a working logger even if nobody called configure().
    """
    global _configured
    if not _configured:
        configure()
    return logging.getLogger(name)
