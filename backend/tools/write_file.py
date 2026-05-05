"""Backend implementation for the write_file tool — writes full content to a file."""

import os

try:
    from config import SANDBOX_WORKSPACE as _WORKSPACE_ROOT
except ImportError:
    _WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.tools._workspace import resolve_workspace_path


def write_file(
    file_path: str,
    content: str,
    overwrite: bool = True,
    create_dirs: bool = True,
) -> dict:
    """
    Write content to a file.

    Args:
        file_path:   Target file path (absolute or relative).
        content:     Full content to write. Written exactly as provided.
        overwrite:   If False, refuse to write if the file already exists.
        create_dirs: If True, create missing parent directories automatically.

    Returns:
        dict with 'result', 'created' on success,
        or 'error' on failure.
    """
    if not file_path:
        return {'error': "Missing required argument: 'file_path'"}
    if content is None:
        return {'error': "Missing required argument: 'content'"}

    abs_path = os.path.abspath(file_path)
    already_exists = os.path.exists(abs_path)

    # Overwrite guard
    if already_exists and not overwrite:
        return {
            'error': (
                f"File already exists: {file_path}. "
                "Set overwrite=true to replace it."
            )
        }

    # Create parent directories
    parent = os.path.dirname(abs_path)
    if parent:
        if not os.path.exists(parent):
            if create_dirs:
                try:
                    os.makedirs(parent, exist_ok=True)
                except PermissionError:
                    return {'error': f"Permission denied creating directories: {parent}"}
                except Exception as e:
                    return {'error': f"Failed to create directories: {e}"}
            else:
                return {
                    'error': (
                        f"Parent directory does not exist: {parent}. "
                        "Set create_dirs=true to create it automatically."
                    )
                }

    # Write
    try:
        encoded = content.encode('utf-8')
        with open(abs_path, 'wb') as f:
            f.write(encoded)
    except PermissionError:
        return {'error': f"Permission denied writing: {file_path}"}
    except IsADirectoryError:
        return {'error': f"Path is a directory, not a file: {file_path}"}
    except Exception as e:
        return {'error': f"Error writing file: {e}"}

    return {
        'result': 'success',
        'bytes_written': len(encoded),
        'created': not already_exists,
    }


def execute(agent, args: dict) -> dict:
    file_path = args.get('file_path')
    content = args.get('content')
    overwrite = args.get('overwrite', True)
    create_dirs = args.get('create_dirs', True)

    # Heuristic safety check: block access to .ssh directory
    if agent is None or agent.get("safety_checker_enabled", 1):
        from backend.tools.safety_checker import check_ssh_path
        ssh_check = check_ssh_path(file_path, agent)
        if ssh_check["blocked"]:
            return {"error": ssh_check["error"]}

    # Heuristic safety check: require approval for SQLite database access
    if not (agent or {}).get('is_super') and (agent is None or agent.get("safety_checker_enabled", 1)):
        from backend.tools.safety_checker import check_sqlite_path
        db_check = check_sqlite_path(file_path, agent)
        if db_check["blocked"]:
            return {
                "error": db_check["error"],
                "level": "requires_approval",
                "reasons": [db_check["reason"]],
                "approval_info": {
                    "risk_level": "medium",
                    "description": "Writing to SQLite database files may corrupt or expose sensitive data.",
                },
            }

    # Normalize booleans in case they arrive as strings from the LLM
    if isinstance(overwrite, str):
        overwrite = overwrite.lower() not in ('false', '0', 'no')
    if isinstance(create_dirs, str):
        create_dirs = create_dirs.lower() not in ('false', '0', 'no')

    if file_path is None:
        return {'error': "Missing required argument: 'file_path'"}
    if content is None:
        return {'error': "Missing required argument: 'content'"}

    # /_self/ path: always route to the agent's local directory on the evonic server.
    from backend.tools._workspace import is_self_path, resolve_self_path
    agent_id = (agent or {}).get('id')
    if agent_id and is_self_path(file_path):
        local_path = resolve_self_path(agent_id, file_path)
        if not local_path:
            return {'error': "Access denied — path escapes agent directory."}
        return write_file(local_path, content, overwrite=overwrite, create_dirs=create_dirs)

    # When sandbox is enabled, route file I/O through the execution backend
    # (Docker container, SSH remote, etc.) instead of the host filesystem.
    sandbox_enabled = (agent or {}).get('sandbox_enabled', 1)
    if sandbox_enabled:
        from backend.tools.lib.exec_backend import registry
        session_id = (agent or {}).get('session_id') or 'default'
        backend = registry.get_backend(session_id, agent)

        # Use the raw path from the agent — the backend runs inside the
        # execution environment (container/remote) where paths like
        # /workspace/… and relative paths resolve correctly.
        target_path = file_path
        already_exists = backend.file_exists(target_path)

        # Overwrite guard
        if not overwrite and already_exists:
            return {
                'error': (
                    f"File already exists: {file_path}. "
                    "Set overwrite=true to replace it."
                )
            }

        # Create parent directories if needed
        if create_dirs:
            parent = os.path.dirname(target_path)
            if parent and parent != '/' and not backend.file_exists(parent):
                result = backend.make_dirs(parent)
                if 'error' in result:
                    return result

        result = backend.write_file(target_path, content, create_dirs=False)
        if 'error' in result:
            return result

        return {
            'result': 'success',
            'bytes_written': len(content.encode('utf-8')),
            'created': not already_exists,
        }

    # No sandbox — direct host filesystem access (original behavior)
    file_path = resolve_workspace_path(agent, file_path, _WORKSPACE_ROOT)
    return write_file(file_path, content, overwrite=overwrite, create_dirs=create_dirs)


# ---------------------------------------------------------------------------
# Self-tests (run with: python3 backend/tools/write_file.py)
# ---------------------------------------------------------------------------

def test_execute():
    import tempfile, shutil

    tmp_dir = tempfile.mkdtemp()
    passed = 0

    def path(*parts):
        return os.path.join(tmp_dir, *parts)

    # ------------------------------------------------------------------
    print('Test 1: Create a new file')
    p = path('hello.txt')
    r = write_file(p, 'hello world\n')
    assert r['result'] == 'success', r
    assert r['created'] is True, r
    assert r['bytes_written'] == len('hello world\n'.encode()), r
    assert open(p).read() == 'hello world\n'
    passed += 1

    # ------------------------------------------------------------------
    print('Test 2: Overwrite an existing file')
    r = write_file(p, 'new content\n')
    assert r['result'] == 'success', r
    assert r['created'] is False, r
    assert open(p).read() == 'new content\n'
    passed += 1

    # ------------------------------------------------------------------
    print('Test 3: overwrite=False blocks existing file')
    r = write_file(p, 'blocked', overwrite=False)
    assert 'error' in r, r
    assert open(p).read() == 'new content\n'  # unchanged
    passed += 1

    # ------------------------------------------------------------------
    print('Test 4: overwrite=False allows creating a new file')
    p2 = path('brand_new.txt')
    r = write_file(p2, 'fresh', overwrite=False)
    assert r['result'] == 'success', r
    assert r['created'] is True, r
    passed += 1

    # ------------------------------------------------------------------
    print('Test 5: create_dirs=True auto-creates nested directories')
    deep = path('a', 'b', 'c', 'deep.txt')
    r = write_file(deep, 'deep content', create_dirs=True)
    assert r['result'] == 'success', r
    assert open(deep).read() == 'deep content'
    passed += 1

    # ------------------------------------------------------------------
    print('Test 6: create_dirs=False fails when parent missing')
    missing = path('nonexistent', 'file.txt')
    r = write_file(missing, 'data', create_dirs=False)
    assert 'error' in r, r
    passed += 1

    # ------------------------------------------------------------------
    print('Test 7: Content preserved exactly (no extra newline)')
    p3 = path('exact.txt')
    r = write_file(p3, 'no trailing newline')
    assert open(p3).read() == 'no trailing newline'
    passed += 1

    # ------------------------------------------------------------------
    print('Test 8: Unicode content written correctly')
    p4 = path('unicode.txt')
    text = 'Héllo wörld — 日本語 🎉\n'
    r = write_file(p4, text)
    assert r['result'] == 'success', r
    assert open(p4, encoding='utf-8').read() == text
    passed += 1

    # ------------------------------------------------------------------
    print('Test 9: Empty content is valid')
    p5 = path('empty.txt')
    r = write_file(p5, '')
    assert r['result'] == 'success', r
    assert r['bytes_written'] == 0, r
    assert open(p5).read() == ''
    passed += 1

    # ------------------------------------------------------------------
    print('Test 10: Missing file_path returns error')
    r = write_file('', 'data')
    assert 'error' in r, r
    passed += 1

    # ------------------------------------------------------------------
    print('Test 11: Missing content returns error')
    r = write_file(path('x.txt'), None)
    assert 'error' in r, r
    passed += 1

    # ------------------------------------------------------------------
    print('Test 12: String boolean args normalised (LLM may send strings)')
    p6 = path('strflag.txt')
    r = execute({'sandbox_enabled': 0}, {'file_path': p6, 'content': 'ok', 'overwrite': 'true', 'create_dirs': 'true'})
    assert r['result'] == 'success', r
    r2 = execute({'sandbox_enabled': 0}, {'file_path': p6, 'content': 'blocked', 'overwrite': 'false'})
    assert 'error' in r2, r2
    passed += 1

    # Cleanup
    shutil.rmtree(tmp_dir)
    print(f'\nAll {passed} tests passed!')


if __name__ == '__main__':
    test_execute()
