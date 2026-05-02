"""Backend implementation for the patch tool — applies unified diff patches to files.

Primary backend: system `patch` utility (used when available on PATH).
Fallback backend: pure-Python implementation that is reliable for all hunk types,
including insertion-only hunks with no surrounding context.
"""

import os
import re
import shutil
import subprocess
import tempfile

from backend.tools._workspace import resolve_workspace_path

SEARCH_WINDOW = 50


# ---------------------------------------------------------------------------
# Patch parser
# ---------------------------------------------------------------------------

def parse_hunks(patch_text: str) -> list:
    """
    Parse a unified diff string into a list of hunk dicts.

    Each hunk:
        {
            'old_start': int,   # 1-based line number in original
            'old_count': int,
            'new_start': int,
            'new_count': int,
            'lines': list of (op, content, no_newline)
                op: ' ' context, '-' remove, '+' add
                content: str without prefix and without trailing newline
                no_newline: True if followed by \\ No newline marker
        }
    """
    hunks = []
    current_hunk = None

    for raw_line in patch_text.splitlines():
        line = raw_line.rstrip('\r\n')

        if re.match(r'^(diff --git|index |old mode|new mode|deleted file|new file)', line):
            continue

        if line.startswith('--- ') or line.startswith('+++ '):
            if current_hunk is not None:
                hunks.append(current_hunk)
                current_hunk = None
            continue

        hunk_match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if hunk_match:
            if current_hunk is not None:
                hunks.append(current_hunk)
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
            current_hunk = {
                'old_start': old_start,
                'old_count': old_count,
                'new_start': new_start,
                'new_count': new_count,
                'lines': [],
            }
            continue

        if current_hunk is None:
            continue

        if line.startswith('\\ '):
            if current_hunk['lines']:
                op, content, _ = current_hunk['lines'][-1]
                current_hunk['lines'][-1] = (op, content, True)
            continue

        if line.startswith('-'):
            current_hunk['lines'].append(('-', line[1:], False))
        elif line.startswith('+'):
            current_hunk['lines'].append(('+', line[1:], False))
        elif line.startswith(' '):
            current_hunk['lines'].append((' ', line[1:], False))
        else:
            current_hunk['lines'].append((' ', line, False))

    if current_hunk is not None:
        hunks.append(current_hunk)

    return hunks


# ---------------------------------------------------------------------------
# Pure-Python fallback helpers
# ---------------------------------------------------------------------------

def _find_first_anchor(lines: list, hunk_lines: list) -> int:
    """
    Scan the file for the first context/removal line from the hunk.
    Used to build helpful error hints.
    Returns 0-based index, or -1 if not found.
    `lines` may contain line endings (readlines output) or bare strings.
    """
    for op, txt, _ in hunk_lines:
        if op in (' ', '-'):
            needle = txt.rstrip()
            for i, line in enumerate(lines):
                if line.rstrip('\r\n').rstrip() == needle:
                    return i
            break  # only search for the very first context/removal line
    return -1


def _find_hunk_pos(lines: list, hunk_lines: list, stated_pos: int,
                   fuzzy: bool = True) -> tuple:
    """
    Find the 0-based position in `lines` where the hunk should be applied.

    For insertion-only hunks (no context or removal lines) the stated position
    is trusted directly — no search is needed.

    For hunks with context/removal lines, searches outward from `stated_pos`
    within ±SEARCH_WINDOW lines, comparing after stripping trailing whitespace.

    `lines` may contain line endings or bare strings — both are handled.

    Returns (pos, None) on success, (-1, None) if no match found.
    """
    to_match = [(op, txt) for op, txt, _ in hunk_lines if op in (' ', '-')]

    # Insertion-only: no context to verify, trust the stated line number.
    if not to_match:
        pos = max(0, min(stated_pos, len(lines)))
        return (pos, None)

    window = SEARCH_WINDOW if fuzzy else 0

    for delta in range(window + 1):
        for sign in ([0] if delta == 0 else [1, -1]):
            pos = stated_pos + sign * delta
            if pos < 0 or pos + len(to_match) > len(lines):
                continue
            if all(
                lines[pos + i].rstrip('\r\n').rstrip() == to_match[i][1].rstrip()
                for i in range(len(to_match))
            ):
                return (pos, None)

    return (-1, None)


def _apply_hunks_to_content(raw: str, patch_text: str) -> dict:
    """Pure-Python hunk application on a raw content string.

    Same logic as apply_hunks() but operates on an in-memory string
    instead of reading/writing a file. Used by the sandboxed code path
    where file I/O goes through the execution backend.
    Returns {'result': 'success', 'content': str, 'hunks_applied': int}
    or {'error': str}.
    """
    hunks = parse_hunks(patch_text)
    if not hunks:
        return {'error': 'No valid hunks found in patch. Make sure it contains @@ hunk headers. For simple edits, consider using str_replace instead.'}

    # Detect CRLF and work with LF-normalized content internally.
    crlf = '\r\n' in raw
    content = raw.replace('\r\n', '\n')

    # Split into lines WITHOUT endings, tracking whether file ends with \n.
    if content.endswith('\n'):
        lines = content[:-1].split('\n')
        trailing_newline = True
    elif content:
        lines = content.split('\n')
        trailing_newline = False
    else:
        lines = []
        trailing_newline = False

    offset = 0  # accumulated offset from previously applied hunks

    for hunk in hunks:
        hunk_lines = hunk['lines']

        # ── Insertion-only hunk ──
        if hunk['old_count'] == 0:
            insert_pos = hunk['new_start'] - 1 + offset
            insert_pos = max(0, min(insert_pos, len(lines)))
            new_lines = [txt for op, txt, _ in hunk_lines if op == '+']
            lines = lines[:insert_pos] + new_lines + lines[insert_pos:]
            offset += len(new_lines)
            if new_lines:
                trailing_newline = True
            continue

        # ── Context hunk: find matching position ──
        stated_pos = hunk['old_start'] - 1 + offset
        pos, _ = _find_hunk_pos(lines, hunk_lines, stated_pos, fuzzy=True)

        if pos == -1:
            anchor = _find_first_anchor(lines, hunk_lines)
            hint = f' (Hint: anchor found at line {anchor + 1})' if anchor >= 0 else ''
            read_offset = max(1, hunk['old_start'] - 20)
            read_hint = f' Use read_file with offset={read_offset} to view content around line {hunk["old_start"]}.'

            for op, txt, _ in hunk_lines:
                if op in (' ', '-') and txt.strip():
                    for line in lines:
                        if (line.rstrip() == txt.strip().rstrip() and
                                line.rstrip() != txt.rstrip()):
                            return {
                                'error': (
                                    f'Context not found at line {hunk["old_start"]} — '
                                    f'possible indentation/tabs/spaces mismatch{hint}. '
                                    'Action: call read_file() to get the current file content, '
                                    f'then reconstruct your patch from scratch.{read_hint}'
                                )
                            }
                    break

            return {
                'error': (
                    f'Context not found for hunk at line {hunk["old_start"]} '
                    f'(searched ±{SEARCH_WINDOW} lines{hint}). '
                    'Action: call read_file() to get the current file content, '
                    f'then reconstruct your patch from scratch.{read_hint}'
                )
            }

        # ── Apply the hunk ──
        result_lines = []
        file_idx = pos
        for op, txt, _ in hunk_lines:
            if op == ' ':
                result_lines.append(lines[file_idx])
                file_idx += 1
            elif op == '-':
                file_idx += 1
            elif op == '+':
                result_lines.append(txt)

        consumed = sum(1 for op, _, _ in hunk_lines if op in (' ', '-'))
        produced = sum(1 for op, _, _ in hunk_lines if op in (' ', '+'))
        lines = lines[:pos] + result_lines + lines[pos + consumed:]
        offset += produced - consumed

    # Reconstruct file content.
    result = '\n'.join(lines)
    if trailing_newline:
        result += '\n'
    if crlf:
        result = result.replace('\n', '\r\n')

    return {'result': 'success', 'content': result, 'hunks_applied': len(hunks)}


def apply_hunks(file_path: str, patch_text: str) -> dict:
    """
    Pure-Python patch application. Used as fallback when the system `patch`
    binary is unavailable.

    Handles:
    - Insertion-only hunks (@@ -N,0 +N,M @@) — inserts at stated position
      without requiring any surrounding context.
    - Context hunks — matched with ±50-line drift tolerance, trailing-whitespace-fuzzy.
    - CRLF line endings — detected and preserved.
    - Files without trailing newline.
    """
    hunks = parse_hunks(patch_text)
    if not hunks:
        return {'error': 'No valid hunks found in patch. Make sure it contains @@ hunk headers. For simple edits, consider using str_replace instead.'}

    creating_new = all(h['old_start'] == 0 and h['old_count'] == 0 for h in hunks)

    if not os.path.exists(file_path):
        if not creating_new:
            return {'error': f'File not found: {file_path}'}
        parent = os.path.dirname(os.path.abspath(file_path))
        os.makedirs(parent, exist_ok=True)
        open(file_path, 'w').close()

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace', newline='') as f:
            raw = f.read()
    except OSError as e:
        return {'error': str(e)}

    # Detect CRLF and work with LF-normalized content internally.
    crlf = '\r\n' in raw
    content = raw.replace('\r\n', '\n')

    # Split into lines WITHOUT endings, tracking whether file ends with \n.
    if content.endswith('\n'):
        lines = content[:-1].split('\n')
        trailing_newline = True
    elif content:
        lines = content.split('\n')
        trailing_newline = False
    else:
        lines = []
        trailing_newline = False

    offset = 0  # accumulated offset from previously applied hunks

    for hunk in hunks:
        hunk_lines = hunk['lines']

        # ── Insertion-only hunk ────────────────────────────────────────────
        if hunk['old_count'] == 0:
            insert_pos = hunk['new_start'] - 1 + offset
            insert_pos = max(0, min(insert_pos, len(lines)))
            new_lines = [txt for op, txt, _ in hunk_lines if op == '+']
            lines = lines[:insert_pos] + new_lines + lines[insert_pos:]
            offset += len(new_lines)
            if new_lines:
                trailing_newline = True
            continue

        # ── Context hunk: find matching position ──────────────────────────
        stated_pos = hunk['old_start'] - 1 + offset
        pos, _ = _find_hunk_pos(lines, hunk_lines, stated_pos, fuzzy=True)

        if pos == -1:
            # Build a helpful error message.
            anchor = _find_first_anchor(lines, hunk_lines)
            hint = f' (Hint: anchor found at line {anchor + 1})' if anchor >= 0 else ''
            read_offset = max(1, hunk['old_start'] - 20)
            read_hint = f' Use read_file with offset={read_offset} to view content around line {hunk["old_start"]}.'

            # Detect indentation mismatch specifically.
            for op, txt, _ in hunk_lines:
                if op in (' ', '-') and txt.strip():
                    for line in lines:
                        if (line.rstrip() == txt.strip().rstrip() and
                                line.rstrip() != txt.rstrip()):
                            return {
                                'error': (
                                    f'Context not found at line {hunk["old_start"]} — '
                                    f'possible indentation/tabs/spaces mismatch{hint}. '
                                    'Action: call read_file() to get the current file content, '
                                    f'then reconstruct your patch from scratch.{read_hint}'
                                )
                            }
                    break

            return {
                'error': (
                    f'Context not found for hunk at line {hunk["old_start"]} '
                    f'(searched ±{SEARCH_WINDOW} lines{hint}). '
                    'Action: call read_file() to get the current file content, '
                    f'then reconstruct your patch from scratch.{read_hint}'
                )
            }

        # ── Apply the hunk ─────────────────────────────────────────────────
        result_lines = []
        file_idx = pos
        for op, txt, _ in hunk_lines:
            if op == ' ':
                result_lines.append(lines[file_idx])
                file_idx += 1
            elif op == '-':
                file_idx += 1
            elif op == '+':
                result_lines.append(txt)

        consumed = sum(1 for op, _, _ in hunk_lines if op in (' ', '-'))
        produced = sum(1 for op, _, _ in hunk_lines if op in (' ', '+'))
        lines = lines[:pos] + result_lines + lines[pos + consumed:]
        offset += produced - consumed

    # Reconstruct file content.
    result = '\n'.join(lines)
    if trailing_newline:
        result += '\n'
    if crlf:
        result = result.replace('\n', '\r\n')

    try:
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            f.write(result)
    except OSError as e:
        return {'error': str(e)}

    return {'result': 'success', 'hunks_applied': len(hunks)}


# ---------------------------------------------------------------------------
# System `patch` binary backend
# ---------------------------------------------------------------------------

def _apply_with_binary(file_path: str, patch_text: str, hunks: list) -> dict:
    """Apply patch using the system `patch` utility."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.patch', delete=False, encoding='utf-8'
    ) as tf:
        # system patch binary requires the patch file to end with a newline
        tf.write(patch_text if patch_text.endswith('\n') else patch_text + '\n')
        patch_file = tf.name

    try:
        proc = subprocess.run(
            [
                'patch',
                '--forward',               # don't try to reverse-apply
                '--no-backup-if-mismatch', # no .orig files
                '--reject-file=/dev/null', # discard .rej files
                file_path,
                patch_file,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return {'result': 'success', 'hunks_applied': len(hunks)}
        output = '\n'.join(filter(None, [proc.stdout.strip(), proc.stderr.strip()]))
        return {'error': f'patch failed:\n{output}'}
    finally:
        try:
            os.unlink(patch_file)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_patch(file_path: str, patch_text: str) -> dict:
    """
    Apply a unified diff patch to a file.

    Uses the system `patch` utility if available on PATH; otherwise falls back
    to the pure-Python implementation (`apply_hunks`).
    """
    try:
        hunks = parse_hunks(patch_text)
    except Exception as e:
        return {'error': f'Failed to parse patch: {e}'}

    if not hunks:
        return {'error': 'No valid hunks found in patch. Make sure it contains @@ hunk headers. For simple edits, consider using str_replace instead.'}

    creating_new = all(h['old_start'] == 0 and h['old_count'] == 0 for h in hunks)

    if not os.path.exists(file_path):
        if not creating_new:
            return {'error': f'File not found: {file_path}'}
        parent = os.path.dirname(os.path.abspath(file_path))
        os.makedirs(parent, exist_ok=True)
        open(file_path, 'w').close()

    if shutil.which('patch'):
        result = _apply_with_binary(file_path, patch_text, hunks)
        if 'error' not in result:
            return result
        # Binary patch failed (e.g. mismatched hunk counts from LLM) — fall
        # through to the Python implementation which is more lenient.

    return apply_hunks(file_path, patch_text)


# ---------------------------------------------------------------------------
# Tool entry point
# ---------------------------------------------------------------------------

def execute(agent, args: dict) -> dict:
    file_path = args.get('file_path')
    patch_text = args.get('patch')

    if not file_path:
        return {'error': "Missing required argument: 'file_path'"}
    if patch_text is None:
        return {'error': "Missing required argument: 'patch'"}
    if not isinstance(patch_text, str):
        return {'error': "'patch' must be a string containing unified diff content"}

    # Heuristic safety check: block access to .ssh directory
    if agent is None or agent.get("safety_checker_enabled", 1):
        from backend.tools.safety_checker import check_ssh_path
        ssh_check = check_ssh_path(file_path, agent)
        if ssh_check["blocked"]:
            return {"error": ssh_check["error"]}

    # When sandbox is enabled, route file I/O through the execution backend.
    sandbox_enabled = (agent or {}).get('sandbox_enabled', 1)
    if sandbox_enabled:
        from backend.tools.lib.exec_backend import registry
        session_id = (agent or {}).get('session_id') or 'default'
        backend = registry.get_backend(session_id, agent)

        target_path = file_path
        creating_new = False
        try:
            hunks = parse_hunks(patch_text)
            creating_new = all(h['old_start'] == 0 and h['old_count'] == 0 for h in hunks)
        except Exception:
            pass

        if not backend.file_exists(target_path):
            if not creating_new:
                return {'error': f'File not found: {file_path}'}
            parent = os.path.dirname(target_path)
            if parent:
                backend.make_dirs(parent)

        if creating_new and not backend.file_exists(target_path):
            backend.write_file(target_path, '')

        read_result = backend.read_file(target_path)
        if 'error' in read_result:
            return {'error': read_result['error']}

        result = _apply_hunks_to_content(read_result['content'], patch_text)
        if 'error' in result:
            return result

        wr = backend.write_file(target_path, result['content'])
        if 'error' in wr:
            return {'error': wr['error']}

        return {'result': 'success', 'hunks_applied': result.get('hunks_applied', 0)}

    # No sandbox — direct host filesystem access (original behavior)
    workspace_root = None
    if file_path and (file_path.startswith('/workspace') or not os.path.isabs(file_path)):
        agent_workspace = (agent or {}).get('workspace')
        if file_path.startswith('/workspace') or agent_workspace:
            from config import SANDBOX_WORKSPACE as _ws
            fallback = _ws
            resolved = resolve_workspace_path(agent, file_path, fallback)
            if resolved != file_path:
                workspace_root = os.path.abspath(agent_workspace or fallback)
                file_path = resolved

    result = apply_patch(file_path, patch_text)

    # Replace absolute host paths in error messages with /workspace-relative paths
    # so agents running inside a container see paths they understand.
    if workspace_root and 'error' in result:
        result['error'] = result['error'].replace(workspace_root, '/workspace')

    return result


# ---------------------------------------------------------------------------
# Self-tests (run with: python backend/tools/patch.py)
# ---------------------------------------------------------------------------

def test_execute():
    import tempfile

    def make_file(content):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        f.write(content)
        f.close()
        return f.name

    def read_file(path):
        with open(path, encoding='utf-8') as f:
            return f.read()

    passed = 0

    print('Test 1: Replace a line')
    tmp = make_file('line one\nline two\nline three\n')
    r = apply_patch(tmp, '@@ -1,3 +1,3 @@\n line one\n-line two\n+line TWO\n line three\n')
    assert r == {'result': 'success', 'hunks_applied': 1}, r
    assert read_file(tmp) == 'line one\nline TWO\nline three\n'
    passed += 1

    print('Test 2: Insert lines')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('alpha\nbeta\ngamma\n')
    r = apply_patch(tmp, '@@ -1,2 +1,4 @@\n alpha\n+inserted1\n+inserted2\n beta\n')
    assert r['result'] == 'success', r
    assert read_file(tmp) == 'alpha\ninserted1\ninserted2\nbeta\ngamma\n'
    passed += 1

    print('Test 3: Insertion-only hunk (no context at all)')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('line1\nline2\nline3\n')
    r = apply_hunks(tmp, '@@ -2,0 +2,2 @@\n+new_a\n+new_b\n')
    assert r['result'] == 'success', r
    assert read_file(tmp) == 'line1\nnew_a\nnew_b\nline2\nline3\n'
    passed += 1

    print('Test 4: Create new file')
    new_path = tmp + '.new'
    if os.path.exists(new_path):
        os.unlink(new_path)
    r = apply_patch(new_path, '@@ -0,0 +1,3 @@\n+first line\n+second line\n+third line\n')
    assert r['result'] == 'success', r
    assert read_file(new_path) == 'first line\nsecond line\nthird line\n'
    os.unlink(new_path)
    passed += 1

    print('Test 5: Multiple hunks')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('a\nb\nc\nd\ne\nf\n')
    r = apply_patch(tmp, '@@ -1,2 +1,2 @@\n a\n-b\n+B\n@@ -5,2 +5,2 @@\n e\n-f\n+F\n')
    assert r['result'] == 'success', r
    assert read_file(tmp) == 'a\nB\nc\nd\ne\nF\n'
    passed += 1

    print('Test 6: Context mismatch → error (Python fallback)')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('line1\nline2\nline3\n')
    r = apply_hunks(tmp, '@@ -1,2 +1,2 @@\n WRONG_CONTEXT\n-line2\n+LINE2\n')
    assert 'error' in r, r
    passed += 1

    print('Test 7: Git-style headers skipped')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('foo\nbar\n')
    patch = 'diff --git a/f b/f\nindex a..b 100644\n--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n foo\n-bar\n+BAR\n'
    r = apply_patch(tmp, patch)
    assert r['result'] == 'success', r
    assert read_file(tmp) == 'foo\nBAR\n'
    passed += 1

    print('Test 8: CRLF preserved (Python fallback)')
    p2 = tempfile.mktemp(suffix='.txt')
    with open(p2, 'w', encoding='utf-8', newline='') as f:
        f.write('line1\r\nline2\r\nline3\r\n')
    r = apply_hunks(p2, '@@ -2,1 +2,1 @@\n-line2\n+LINE2\n')
    assert r['result'] == 'success', r
    raw = open(p2, 'rb').read()
    assert b'\r\n' in raw, 'CRLF should be preserved'
    os.unlink(p2)
    passed += 1

    print('Test 9: File not found → error')
    r = apply_patch('/nonexistent/path/file.txt', '@@ -1,1 +1,1 @@\n-x\n+y\n')
    assert 'error' in r, r
    passed += 1

    print('Test 10: No hunks → error')
    r = apply_patch(tmp, 'not a patch')
    assert 'error' in r, r
    passed += 1

    print('Test 11: Implicit hunk count=1')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('only line\n')
    r = apply_patch(tmp, '@@ -1 +1 @@\n-only line\n+ONLY LINE\n')
    assert r['result'] == 'success', r
    assert read_file(tmp) == 'ONLY LINE\n'
    passed += 1

    print('Test 12: Python fallback drift tolerance (±50 lines)')
    lines = [f'filler_{i}\n' for i in range(44)]
    lines += ['target line\n', 'after target\n']
    with open(tmp, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    r = apply_hunks(tmp, '@@ -1,2 +1,2 @@\n target line\n-after target\n+REPLACED\n')
    assert r['result'] == 'success', r
    assert 'REPLACED' in read_file(tmp)
    passed += 1

    os.unlink(tmp)
    print(f'\nAll {passed} tests passed!')


if __name__ == '__main__':
    test_execute()
