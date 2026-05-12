"""
_portal.py — portal virtual path resolution for file tools.

Intercepts /_portal/... paths and resolves them to real paths routed through
the appropriate backend (local, SSH, evonet).
"""

import json
import os
import threading


_PORTAL_PREFIX = "/_portal/"


def is_portal_path(file_path: str) -> bool:
    """Return True if file_path starts with the /_portal/ virtual prefix."""
    return bool(file_path) and (file_path.startswith(_PORTAL_PREFIX) or file_path == "/_portal")


# In-memory cache for agent portal lookups, invalidated on portal CRUD.
# Structure: { agent_id: { "portals": [...], "loaded_at": timestamp } }
_portal_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 30  # seconds


def invalidate_portal_cache(agent_id: str = None):
    """Invalidate the portal cache for an agent, or all agents if None."""
    with _cache_lock:
        if agent_id is None:
            _portal_cache.clear()
        else:
            _portal_cache.pop(agent_id, None)


def resolve_portal_path(agent_id: str, file_path: str) -> tuple:
    """Resolve a /_portal/... path to a (backend, real_path) tuple.

    Returns:
        (ExecutionBackend, str) on success
        (None, str) on failure — str is an error message
    """
    if not agent_id:
        return (None, "Portal paths require an agent context.")

    # Strip the /_portal/ prefix
    sub_path = file_path[len(_PORTAL_PREFIX):] if file_path.startswith(_PORTAL_PREFIX) else ""
    if not sub_path:
        return (None, "Invalid portal path — no virtual path specified after /_portal/.")

    # Load agent's portals (with caching)
    portals = _load_agent_portals(agent_id)
    if not portals:
        return (None, f"No portals configured for agent '{agent_id}'. "
                      f"Use read_file on regular paths or configure a portal.")

    # Find the longest virtual_path prefix match
    best_match = None
    best_vpath = ""
    for portal in portals:
        vpath = portal.get("virtual_path", "")
        # Match if sub_path starts with vpath, and vpath is at a path boundary
        # (i.e., sub_path == vpath, or sub_path starts with vpath + "/")
        if sub_path == vpath or (sub_path.startswith(vpath + "/") and len(vpath) > len(best_vpath)):
            best_match = portal
            best_vpath = vpath

    if best_match is None:
        return (None, f"No portal matches virtual path '{sub_path}'. "
                      f"Available portals: {[p['virtual_path'] for p in portals]}")

    # Strip matched virtual_path prefix from sub_path
    remainder = sub_path[len(best_vpath):].lstrip("/")
    real_path = os.path.join(best_match.get("real_path", ""), remainder)

    # Get or create the backend
    from backend.portals.manager import portal_manager
    try:
        backend = portal_manager.get_backend(best_match)
    except RuntimeError as e:
        return (None, str(e))

    return (backend, real_path)


def _load_agent_portals(agent_id: str) -> list:
    """Load agent's portals from DB, cached for CACHE_TTL seconds."""
    now = __import__("time").time()

    with _cache_lock:
        cached = _portal_cache.get(agent_id)
        if cached and (now - cached.get("loaded_at", 0)) < _CACHE_TTL:
            return cached["portals"]

    from models.db import db
    portals = db.get_agent_portals(agent_id)

    # Parse backend_config from JSON strings to dicts for easier use
    for p in portals:
        cfg = p.get("backend_config", {})
        if isinstance(cfg, str):
            try:
                p["backend_config"] = json.loads(cfg)
            except (json.JSONDecodeError, TypeError):
                p["backend_config"] = {}

    # Sort by virtual_path length descending for longest-prefix-first matching
    portals.sort(key=lambda p: len(p.get("virtual_path", "")), reverse=True)

    with _cache_lock:
        _portal_cache[agent_id] = {"portals": portals, "loaded_at": now}

    return portals
