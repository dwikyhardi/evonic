"""
evonic.files — bulk file operations and patch application.
"""

import glob as _glob
import json as _json
import os
import subprocess
import tempfile


# ---------------------------------------------------------------------------
# patch
# ---------------------------------------------------------------------------

def patch(patch_text: str, path: str = '.', strip: int = 1,
          dry_run: bool = False) -> dict:
    """Apply a unified diff patch using the system `patch` command.

    Args:
        patch_text: Unified diff text (e.g. from `git diff` or `diff -u`).
        path:       Directory to apply the patch in (default: current).
        strip:      Number of path prefix components to strip (default: 1,
                    same as `patch -p1`).
        dry_run:    If True, check without modifying files (default: False).

    Returns:
        dict with keys:
            ok (bool), output (str), rejected_files (list)

    Example:
        from evonic.files import patch
        patch(open('/workspace/fix.patch').read())
    """
    path = os.path.abspath(path)

    # Prevent path traversal outside /workspace
    workspace = os.path.abspath('/workspace')
    if not path.startswith(workspace):
        return {'ok': False, 'output': f'path must be inside {workspace}', 'rejected_files': []}

    # Snapshot pre-existing .rej files so we only report new ones
    preexisting_rej = set()
    for root, _, files_list in os.walk(path):
        for fname in files_list:
            if fname.endswith('.rej'):
                preexisting_rej.add(os.path.relpath(os.path.join(root, fname), path))

    # Write patch text to a temp file (explicit UTF-8 to handle non-ASCII content)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False,
                                     encoding='utf-8') as f:
        f.write(patch_text if patch_text.endswith('\n') else patch_text + '\n')
        patch_path = f.name

    try:
        cmd = ['patch', f'-p{strip}', '--batch']
        if dry_run:
            cmd.append('--dry-run')
        cmd += ['-i', patch_path]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=path, timeout=30)
        except FileNotFoundError:
            return {'ok': False, 'output': '`patch` command not found. Install it with: apt-get install patch', 'rejected_files': []}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'output': 'patch timed out', 'rejected_files': []}

        # Find only .rej files created by this patch run
        rejected = []
        for root, _, files_list in os.walk(path):
            for fname in files_list:
                if fname.endswith('.rej'):
                    rel = os.path.relpath(os.path.join(root, fname), path)
                    if rel not in preexisting_rej:
                        rejected.append(rel)

        return {
            'ok': r.returncode == 0 and not rejected,
            'output': (r.stdout + r.stderr).strip(),
            'rejected_files': rejected,
        }
    finally:
        try:
            os.unlink(patch_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------

def str_replace(file_path: str, old_str: str, new_str: str, count: int = 1) -> dict:
    """Replace an exact string occurrence in a file.

    Unlike patch(), this function does not require line numbers — it finds the
    literal text and replaces it. More reliable for simple targeted edits.

    Args:
        file_path: Path to the file to edit.
        old_str:   The exact text to find and replace. Must be unique in the
                   file (or match exactly `count` times). Include enough
                   surrounding context to make it unambiguous.
        new_str:   The replacement text. Use an empty string to delete old_str.
        count:     Number of replacements to make (default 1). If the file
                   contains a different number of occurrences than `count`,
                   an error is returned.

    Returns:
        dict with 'result' and 'replacements' on success, or 'error' on failure.

    Example:
        from evonic.files import str_replace
        str_replace('/workspace/app.py', 'old_function_name', 'new_function_name')
    """
    if not old_str:
        return {'error': "'old_str' must not be empty"}

    if not os.path.exists(file_path):
        return {'error': f'File not found: {file_path}'}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        return {'error': str(e)}

    occurrences = content.count(old_str)

    if occurrences == 0:
        return {
            'error': (
                f"'old_str' not found in {file_path}. "
                'Action: call read_file() to get the current file content '
                'and copy the exact text you want to replace.'
            )
        }

    if occurrences != count:
        return {
            'error': (
                f"'old_str' found {occurrences} time(s) in {file_path}, "
                f'but count={count}. '
                "Make 'old_str' more specific by including more surrounding context, "
                f'or set count={occurrences} if you intend to replace all occurrences.'
            )
        }

    new_content = content.replace(old_str, new_str, count)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    except OSError as e:
        return {'error': str(e)}

    return {'result': 'success', 'replacements': count}


# ---------------------------------------------------------------------------
# batch_rename
# ---------------------------------------------------------------------------

def batch_rename(glob_pattern: str, rename_fn, path: str = '.', dry_run: bool = True) -> list:
    """Rename files matching a glob using a rename function.

    Args:
        glob_pattern: Glob filter (e.g. '*.txt').
        rename_fn:    Callable(old_name: str) -> new_name: str
        path:         Root directory (default: current).
        dry_run:      If True (default), only preview changes without renaming.

    Returns:
        List of dicts: [{from, to, action}] where action is 'rename', 'skip'
        (same name), or 'dry_run'.

    Example:
        batch_rename('*.jpeg', lambda n: n.replace('.jpeg', '.jpg'))
    """
    path = os.path.abspath(path)
    matches = _glob.glob(os.path.join(path, glob_pattern))
    results = []

    for fpath in sorted(matches):
        if not os.path.isfile(fpath):
            continue
        old_name = os.path.basename(fpath)
        new_name = rename_fn(old_name)
        if old_name == new_name:
            results.append({'from': old_name, 'to': new_name, 'action': 'skip'})
            continue
        new_path = os.path.join(os.path.dirname(fpath), new_name)
        if dry_run:
            results.append({'from': old_name, 'to': new_name, 'action': 'dry_run'})
        else:
            os.rename(fpath, new_path)
            results.append({'from': old_name, 'to': new_name, 'action': 'rename'})

    return results


# ---------------------------------------------------------------------------
# template
# ---------------------------------------------------------------------------

def template(text: str, **vars) -> str:
    """Simple {var} string templating.

    Args:
        text: Template string with {placeholder} markers.
        **vars: Values to substitute.

    Returns:
        Rendered string.

    Example:
        result = template("Hello {name}, you are {age}!", name="Alice", age=30)
    """
    return text.format(**vars)
