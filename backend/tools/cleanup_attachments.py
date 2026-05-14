"""Real backend implementation for the cleanup_attachments tool.

Restricted to super agents. Calls db.cleanup_expired_attachments and returns the
deleted-row count and freed disk bytes.
"""

from typing import Any, Dict


def execute(agent, args: dict) -> Dict[str, Any]:
    agent = agent or {}
    if not agent.get('is_super'):
        return {"error": "Not authorized — cleanup_attachments requires a super agent."}

    older_than_days = args.get('older_than_days')
    if older_than_days is None:
        older_than_days = 7
    try:
        older_than_days = int(older_than_days)
    except (TypeError, ValueError):
        return {"error": "Invalid 'older_than_days' — must be an integer."}
    if older_than_days < 0:
        return {"error": "Invalid 'older_than_days' — must be >= 0."}

    from models.db import db
    deleted, freed = db.cleanup_expired_attachments(max_age_days=older_than_days)
    return {
        "result": {
            "deleted_count": int(deleted),
            "freed_bytes": int(freed),
            "older_than_days": older_than_days,
        }
    }
