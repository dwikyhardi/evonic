"""
_workspace.py — shared workspace path resolution for file tools.
"""

import os


def resolve_workspace_path(agent, file_path: str, fallback_workspace: str) -> str:
    """Resolve a file path to an absolute path, honoring the agent's workspace.

    Rules (in priority order):
    1. If path starts with '/workspace', strip that prefix and join with the
       agent's workspace (or fallback_workspace).  This is the runpy-sandbox
       convention for paths inside a Docker container.
    2. If path is relative (not absolute) and the agent has a workspace set,
       resolve it relative to that workspace.
    3. Otherwise return the path unchanged.
    """
    if not file_path:
        return file_path

    if file_path.startswith('/workspace'):
        workspace_root = (agent or {}).get('workspace') or fallback_workspace
        rel = file_path[len('/workspace'):].lstrip('/')
        return os.path.join(os.path.abspath(workspace_root), rel)

    if not os.path.isabs(file_path):
        workspace = (agent or {}).get('workspace')
        if workspace:
            return os.path.join(os.path.abspath(workspace), file_path)

    return file_path
