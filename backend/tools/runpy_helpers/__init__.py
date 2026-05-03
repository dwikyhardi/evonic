"""
evonic — pre-installed helpers for the runpy Docker sandbox.

Usage inside runpy:
    from evonic import display, http
    from evonic import tree, find, stats
"""

import fnmatch
import os
import subprocess
from pathlib import PurePosixPath

# Absolute path to the bundled native binaries directory (evonic/bin/).
# Resolves correctly inside the container regardless of where the package is mounted.
BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin')

from evonic import display, http

__all__ = ['display', 'http', 'BIN_DIR',
           'tree', 'find', 'stats']


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------

def _load_gitignore_patterns(path: str) -> list:
    patterns = []
    gi = os.path.join(path, '.gitignore')
    if os.path.isfile(gi):
        with open(gi, errors='replace') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)
    return patterns


def _is_ignored(name: str, patterns: list) -> bool:
    """Check if *name* matches any gitignore pattern.

    name is ALWAYS a bare name (no path separators). For file filtering
    the caller passes both fname and full relpath as separate calls;
    this function handles both cases correctly via the presence of '/'
    in the pattern itself.

    Key difference from fnmatch: gitignore ``*`` does NOT cross ``/``.
    We use PurePosixPath.match() for patterns containing ``/`` to get
    the correct boundary behavior.
    """
    for pat in patterns:
        # Skip negation patterns — we don't support un-ignore
        if pat.startswith('!'):
            continue
        # Strip trailing slash (directory-only marker)
        clean = pat.rstrip('/')
        if not clean:
            continue
        if '/' in clean:
            # Pattern contains a path separator.
            if clean.endswith('/**'):
                # gitignore: `dir/**` matches everything under `dir/`
                # pathlib.match() does NOT handle ** as a final component,
                # so we match by prefix.
                prefix = clean[:-3]
                if name == prefix or name.startswith(prefix + '/'):
                    return True
            elif PurePosixPath(name).match(clean):
                # PurePosixPath.match() correctly prevents * from crossing /
                # boundaries, unlike fnmatch which lets * match / in 3.11+.
                return True
        else:
            # Pattern has no separator: match against the basename.
            # This mirrors gitignore behavior where patterns without /
            # match at any directory depth against the filename only.
            if fnmatch.fnmatch(name, clean):
                return True
    return False


def tree(path: str = '.', depth: int = 3, ignore: list = None) -> str:
    """Return a directory tree as a formatted string.

    Args:
        path:   Root directory (default: current directory).
        depth:  Maximum depth to recurse (default: 3).
        ignore: Additional glob patterns to skip (e.g. ['*.pyc', '__pycache__']).

    Returns:
        Multi-line string with tree structure.
    """
    path = os.path.abspath(path)
    gi_patterns = _load_gitignore_patterns(path)
    extra = list(ignore or [])
    skip = set(['__pycache__', '.git', '.cache', '.mypy_cache', '.pytest_cache', 'node_modules',
                '.venv', 'venv', '.tox', 'dist', 'build', '*.pyc', '*.pyo'])
    all_ignore = list(skip) + gi_patterns + extra

    lines = [os.path.basename(path) + '/']

    def _walk(cur_path: str, prefix: str, cur_depth: int):
        if cur_depth > depth:
            return
        try:
            entries = sorted(os.scandir(cur_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if not _is_ignored(e.name, all_ignore)]
        for i, entry in enumerate(entries):
            connector = '└── ' if i == len(entries) - 1 else '├── '
            suffix = '/' if entry.is_dir() else ''
            lines.append(f'{prefix}{connector}{entry.name}{suffix}')
            if entry.is_dir():
                extension = '    ' if i == len(entries) - 1 else '│   '
                _walk(entry.path, prefix + extension, cur_depth + 1)

    _walk(path, '', 1)
    lines.insert(0, f'(cwd: {path})')
    result = '\n'.join(lines)
    print(result)
    return result



# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

def find(glob_pattern: str, path: str = '.') -> list:
    """Find files matching a glob pattern.

    Args:
        glob_pattern: Glob pattern (e.g. '**/*.py', '*.json').
        path:         Root directory to search (default: current).

    Returns:
        Sorted list of relative file paths.
    """
    path = os.path.abspath(path)
    EXCLUDE_DIRS = {'.cache', '.git', 'node_modules', '__pycache__', 'site-packages',
                    '.venv', 'venv', '.pup_pkgs', 'build', 'output', 'logs'}

    # Honor .gitignore at the root
    gi_patterns = _load_gitignore_patterns(path)

    results = []
    for root, dirs, files_list in os.walk(path):
        # Prune excluded directories in-place (hardcoded + gitignore)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not _is_ignored(d, gi_patterns)]
        for fname in files_list:
            fpath = os.path.join(root, fname)
            if not os.path.isfile(fpath):
                continue
            rel = os.path.relpath(fpath, path)
            # Skip files ignored by .gitignore
            if _is_ignored(fname, gi_patterns) or _is_ignored(rel, gi_patterns):
                continue
            # fnmatch handles ** via regex expansion and works on Python 3.11+
            if fnmatch.fnmatch(rel, glob_pattern):
                results.append(rel)

    return sorted(results)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def stats(path: str = '.') -> dict:
    """Return a summary of the workspace.

    Returns:
        dict with keys: total_files, total_size_kb, by_extension (dict),
        git_branch (str or None), path (str).
    """
    path = os.path.abspath(path)
    by_ext: dict = {}
    total_files = 0
    total_size = 0

    for root, dirs, files_list in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules')]
        for fname in files_list:
            fpath = os.path.join(root, fname)
            _, ext = os.path.splitext(fname)
            ext = ext.lower() or '(no ext)'
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = 0
            by_ext[ext] = by_ext.get(ext, 0) + 1
            total_files += 1
            total_size += size

    # Sort by count desc
    by_ext = dict(sorted(by_ext.items(), key=lambda x: -x[1]))

    # Git branch
    git_branch = None
    try:
        r = subprocess.run(['git', '-C', path, 'rev-parse', '--abbrev-ref', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            git_branch = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {
        'path': path,
        'total_files': total_files,
        'total_size_kb': round(total_size / 1024, 1),
        'by_extension': by_ext,
        'git_branch': git_branch,
    }


# ---------------------------------------------------------------------------
# Helper registry (used by runpy to inject available_helpers on first call)
# ---------------------------------------------------------------------------

def _registry() -> dict:
    """Return a mapping of module name -> list of public function names."""
    import inspect
    import sys as _sys
    _self = _sys.modules[__name__]
    modules = {
        'evonic.display': display,
        'evonic.http': http,
    }
    result = {}
    # Top-level evonic functions (tree, find, stats)
    top_fns = sorted(
        fn for fn in dir(_self)
        if not fn.startswith('_')
        and callable(getattr(_self, fn))
        and inspect.isfunction(getattr(_self, fn))
        and getattr(getattr(_self, fn), '__module__', '') == __name__
    )
    if top_fns:
        result['evonic'] = top_fns
    for name, mod in modules.items():
        fns = [
            fn for fn in dir(mod)
            if not fn.startswith('_')
            and callable(getattr(mod, fn))
            and inspect.isfunction(getattr(mod, fn))
        ]
        result[name] = fns
    return result
