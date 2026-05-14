"""
LocalPortalBackend — wraps direct local filesystem access as an ExecutionBackend.

Portals only support file I/O — run_bash and run_python raise NotImplementedError.
"""

import os

from backend.tools.lib.exec_backend import ExecutionBackend


class LocalPortalBackend(ExecutionBackend):
    """Wraps direct host filesystem access for a local portal."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def file_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def file_stat(self, path: str) -> dict:
        if not os.path.exists(path):
            return {"exists": False, "size": 0, "is_binary": False}
        size = os.path.getsize(path)
        is_binary = False
        if size > 0:
            try:
                with open(path, "rb") as f:
                    is_binary = b"\x00" in f.read(8192)
            except Exception:
                pass
        return {"exists": True, "size": size, "is_binary": is_binary}

    def read_file(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return {"content": f.read()}
        except PermissionError:
            return {"error": "Permission denied — cannot read this file."}
        except UnicodeDecodeError:
            return {"error": "File contains non-UTF-8 characters."}
        except Exception as e:
            return {"error": str(e)}

    def write_file(self, path: str, content: str, create_dirs: bool = True) -> dict:
        try:
            if create_dirs:
                parent = os.path.dirname(path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True}
        except PermissionError:
            return {"error": f"Permission denied writing: {path}"}
        except IsADirectoryError:
            return {"error": f"Path is a directory, not a file: {path}"}
        except Exception as e:
            return {"error": str(e)}

    def make_dirs(self, path: str) -> dict:
        try:
            os.makedirs(path, exist_ok=True)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Path resolution — identity (noop)
    # ------------------------------------------------------------------

    def resolve_path(self, path: str) -> str:
        return path

    # ------------------------------------------------------------------
    # Execution — not supported for portals
    # ------------------------------------------------------------------

    def run_bash(self, script: str, timeout: int, env: dict) -> dict:
        raise NotImplementedError(
            "Portals do not support run_bash. Use the file I/O tools instead."
        )

    def run_python(self, code: str, timeout: int, env: dict) -> dict:
        raise NotImplementedError(
            "Portals do not support run_python. Use the file I/O tools instead."
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def destroy(self) -> dict:
        return {"result": "ok", "detail": "LocalPortalBackend released."}

    def status(self) -> dict:
        return {"backend": "local_portal"}
