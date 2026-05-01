"""
evonic.shell — subprocess wrapper for running shell commands.
"""

import os
import shlex
import shutil
import os.path
import subprocess
from typing import NamedTuple, Optional


class ShellResult(NamedTuple):
    stdout: str
    stderr: str
    exit_code: int
    ok: bool

    def __str__(self):
        parts = []
        if self.stdout:
            parts.append(self.stdout.rstrip())
        if self.stderr:
            parts.append(f'[stderr] {self.stderr.rstrip()}')
        if not self.ok:
            parts.append(f'[exit {self.exit_code}]')
        return '\n'.join(parts) if parts else ''

    def print(self):
        """Print stdout (and stderr/exit_code if non-zero) to stdout."""
        text = str(self)
        if text:
            print(text)
        return self


def _resolve_tool(name: str) -> str:
    """Prefer bundled binary in evonic/bin/ over the system PATH.

    Matches the same logic used by evonic so that tools like rg
    resolve to the same binary regardless of whether they are called via
    search() or shell.run().
    """
    try:
        from evonic import BIN_DIR
        bundled = os.path.join(BIN_DIR, name)
        if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return bundled
    except ImportError:
        pass
    return name


def run(cmd, timeout: int = 30, cwd: str = None, env: dict = None) -> ShellResult:
    """Run a shell command and return its result.

    Args:
        cmd:     Command string (shell-split) or list of args.
        timeout: Max seconds to wait (default: 30).
        cwd:     Working directory (default: current directory).
        env:     Extra environment variables to merge into the process env.

    Returns:
        ShellResult(stdout, stderr, exit_code, ok)

    Example:
        r = run('git log --oneline -5')
        r.print()
    """
    if isinstance(cmd, str):
        args = shlex.split(cmd)
    else:
        args = list(cmd)

    # Resolve the executable through evonic/bin/ (bundled) before falling back
    # to PATH. This ensures shell.run('rg ...') uses the same binary as
    # search(), avoiding version mismatches with system packages.
    if args:
        args[0] = _resolve_tool(args[0])

    # When rg/grep is called without a path argument and stdin is not a TTY,
    # the tool defaults to searching stdin instead of the filesystem.
    # In a shell environment, a wrapper function auto-appends ".",
    # but subprocess.run() calls the binary directly.  We replicate that
    # convenience here so that shell.run("rg ...") behaves like shell rg ...
    _PATHLESS_SEARCH_TOOLS = {"rg", "grep"}
    if args and os.path.basename(args[0]) in _PATHLESS_SEARCH_TOOLS:
        # For rg/grep, the first non-flag arg is the PATTERN,
        # subsequent non-flag args are paths.  If there are 0 or 1
        # non-flag args, there is no path — append ".".
        positional = [a for a in args[1:] if not a.startswith("-")]
        if len(positional) <= 1:
            args.append(".")

    merged_env = None
    if env:
        merged_env = {**os.environ, **env}

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=merged_env,
        )
        return ShellResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            ok=proc.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        return ShellResult(stdout='', stderr=f'Command timed out after {timeout}s', exit_code=-1, ok=False)
    except FileNotFoundError as e:
        return ShellResult(stdout='', stderr=str(e), exit_code=127, ok=False)
    except Exception as e:
        return ShellResult(stdout='', stderr=str(e), exit_code=-1, ok=False)


def which(name: str) -> Optional[str]:
    """Return the full path of a command, or None if not found.

    Example:
        print(which('rg'))   # '/usr/bin/rg' or None
    """
    return shutil.which(name)
