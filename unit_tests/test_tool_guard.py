"""Unit tests for the plugin tool guard registry and kanban agent guard."""

import json
import pytest


# ─── Tests for the registry in plugin_manager ────────────────────────────────

class TestToolGuardRegistry:
    def setup_method(self):
        # Import here to get the live module-level state; clear guards before each test.
        import backend.plugin_manager as pm
        import backend.plugin_hooks as ph
        self._pm = pm
        self._ph = ph
        ph._tool_guards.clear()

    def teardown_method(self):
        self._ph._tool_guards.clear()

    def test_register_guard(self):
        guard = lambda agent_id, tool_name, args: None
        self._pm.register_tool_guard(guard)
        assert guard in self._ph._tool_guards

    def test_register_idempotent(self):
        guard = lambda agent_id, tool_name, args: None
        self._pm.register_tool_guard(guard)
        self._pm.register_tool_guard(guard)
        assert self._ph._tool_guards.count(guard) == 1

    def test_unregister_guard(self):
        guard = lambda agent_id, tool_name, args: None
        self._pm.register_tool_guard(guard)
        self._pm.unregister_tool_guard(guard)
        assert guard not in self._ph._tool_guards

    def test_unregister_nonexistent_is_noop(self):
        guard = lambda agent_id, tool_name, args: None
        self._pm.unregister_tool_guard(guard)  # should not raise

    def test_check_returns_none_when_no_guards(self):
        result = self._pm.check_tool_guards('agent1', 'bash', {})
        assert result is None

    def test_check_returns_none_when_guard_allows(self):
        self._pm.register_tool_guard(lambda a, t, args: None)
        result = self._pm.check_tool_guards('agent1', 'bash', {})
        assert result is None

    def test_check_returns_block_when_guard_blocks(self):
        def blocking_guard(agent_id, tool_name, args):
            return {'block': True, 'error': 'not allowed'}
        self._pm.register_tool_guard(blocking_guard)
        result = self._pm.check_tool_guards('agent1', 'bash', {})
        assert result is not None
        assert result['block'] is True
        assert 'not allowed' in result['error']

    def test_check_stops_at_first_blocking_guard(self):
        called = []

        def guard1(agent_id, tool_name, args):
            called.append('guard1')
            return {'block': True, 'error': 'guard1 blocks'}

        def guard2(agent_id, tool_name, args):
            called.append('guard2')
            return None

        self._pm.register_tool_guard(guard1)
        self._pm.register_tool_guard(guard2)
        result = self._pm.check_tool_guards('agent1', 'bash', {})
        assert result['error'] == 'guard1 blocks'
        assert 'guard2' not in called

    def test_check_skips_raising_guard(self):
        def bad_guard(agent_id, tool_name, args):
            raise RuntimeError('broken')

        def good_guard(agent_id, tool_name, args):
            return {'block': True, 'error': 'good guard blocks'}

        self._pm.register_tool_guard(bad_guard)
        self._pm.register_tool_guard(good_guard)
        # Should not propagate the exception; should still reach good_guard
        result = self._pm.check_tool_guards('agent1', 'bash', {})
        assert result is not None
        assert result['error'] == 'good guard blocks'


# ─── Tests for the kanban-specific guard logic ────────────────────────────────

class TestKanbanToolGuard:
    """Tests for the _tool_guard function in the kanban plugin handler.

    We test the guard logic in isolation without loading the full plugin
    (which starts a scanner thread and tries to connect to external services).
    """

    def setup_method(self):
        # Patch out the heavy module-level side effects so we can import safely.
        import sys
        import types

        # Save original sys.modules entries so teardown can restore them.
        self._saved_agent_runtime = sys.modules.get('backend.agent_runtime')
        self._saved_plugin_manager = sys.modules.get('backend.plugin_manager')

        # Stub out backend.agent_runtime to avoid DB/socket init
        if 'backend.agent_runtime' not in sys.modules:
            sys.modules['backend.agent_runtime'] = types.ModuleType('backend.agent_runtime')

        # Stub out backend.plugin_manager to capture register calls without real state
        if 'backend.plugin_manager' not in sys.modules:
            mod = types.ModuleType('backend.plugin_manager')
            mod.register_tool_guard = lambda fn: None
            sys.modules['backend.plugin_manager'] = mod

        # Reset pending tasks before each test by patching _pending_tasks directly.
        # We need to carefully avoid re-running module-level code (_setup_scheduler).
        # If handler is already loaded, just reset state.
        if 'plugins.kanban.handler' in sys.modules:
            self._handler = sys.modules['plugins.kanban.handler']
        else:
            # Stub out _setup_scheduler so the scheduler doesn't start
            import unittest.mock as mock
            with mock.patch('plugins.kanban.handler._setup_scheduler'):
                import plugins.kanban.handler as h
                self._handler = h

        # Always reset state before each test
        self._handler._pending_tasks.clear()
        self._handler._active_tasks.clear()

    def teardown_method(self):
        # Restore sys.modules to pre-test state so stub modules don't leak
        # into subsequent test files (e.g. test_scheduler, test_tool_registry).
        import sys
        _sentinel = object()
        for key, saved in [
            ('backend.agent_runtime', self._saved_agent_runtime),
            ('backend.plugin_manager', self._saved_plugin_manager),
        ]:
            if saved is _sentinel:
                pass
            elif saved is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = saved

    def _guard(self, agent_id, tool_name, args=None, task_status='todo', autopilot=False):
        """Call _tool_guard with kanban_db.get and autopilot setting mocked."""
        import unittest.mock as mock
        task_id = self._handler._pending_tasks.get(agent_id, 'mock-task')
        fake_task = {'id': task_id, 'status': task_status}
        autopilot_value = '1' if autopilot else '0'
        with mock.patch('plugins.kanban.db.kanban_db') as mock_db, \
             mock.patch('models.db.db') as mock_db2:
            mock_db.get.return_value = fake_task
            mock_db2.get_setting.return_value = autopilot_value
            return self._handler._tool_guard(agent_id, tool_name, args or {})

    # ── No pending task ──────────────────────────────────────────────────────

    def test_allows_any_tool_when_no_pending_task(self):
        result = self._guard('siwa', 'bash', {'cmd': 'ls'})
        assert result is None

    # ── Pending task, allowed tools ──────────────────────────────────────────

    def test_allows_use_skill_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        assert self._guard('siwa', 'use_skill') is None

    def test_allows_kanban_update_status_when_pending(self):
        # kanban_update_status is allowed only when autopilot=ON
        self._handler._pending_tasks['siwa'] = 'task-1'
        assert self._guard('siwa', 'kanban_update_status', autopilot=True) is None

    def test_allows_kanban_update_task_when_pending(self):
        # kanban_update_task is allowed only when autopilot=ON
        self._handler._pending_tasks['siwa'] = 'task-1'
        assert self._guard('siwa', 'kanban_update_task', autopilot=True) is None

    def test_allows_kanban_search_tasks_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        assert self._guard('siwa', 'kanban_search_tasks') is None

    def test_allows_set_mode_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        assert self._guard('siwa', 'set_mode') is None

    # ── Pending task, blocked tools ──────────────────────────────────────────

    def test_blocks_bash_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-99'
        result = self._guard('siwa', 'bash', {'cmd': 'git status'})
        assert result is not None
        assert result['block'] is True
        assert 'task-99' in result['error']
        assert 'kanban:activate' in result['error']

    def test_blocks_write_file_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-2'
        result = self._guard('siwa', 'write_file')
        assert result is not None
        assert result['block'] is True

    def test_blocks_runpy_when_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-3'
        result = self._guard('siwa', 'runpy')
        assert result is not None
        assert result['block'] is True

    def test_block_message_includes_task_id(self):
        self._handler._pending_tasks['agent-x'] = 'my-task-id'
        result = self._guard('agent-x', 'bash')
        assert "my-task-id" in result['error']

    def test_does_not_affect_other_agent(self):
        """Guard for agent-A should not block agent-B."""
        self._handler._pending_tasks['agent-a'] = 'task-5'
        result = self._guard('agent-b', 'bash')
        assert result is None

    # ── on_tool_executed: direct kanban_update_status calls ─────────────────

    def test_kanban_in_progress_clears_pending_and_sets_active(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_status',
            'tool_result': {'task': {'id': 'task-1', 'status': 'in-progress'}},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._pending_tasks
        assert self._handler._active_tasks.get('siwa') == 'task-1'

    def test_kanban_done_clears_active(self):
        self._handler._active_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_status',
            'tool_result': {'task': {'id': 'task-1', 'status': 'done'}},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._active_tasks

    def test_kanban_done_also_clears_pending(self):
        """Agent skipped in-progress step — done should still release the guard."""
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_status',
            'tool_result': {'task': {'id': 'task-1', 'status': 'done'}},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._pending_tasks

    def test_on_tool_executed_ignores_non_kanban_tools(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'bash',
            'tool_result': {'output': 'ok'},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' in self._handler._pending_tasks


    def test_on_tool_executed_handles_json_string_result(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_status',
            'tool_result': json.dumps({'task': {'id': 'task-1', 'status': 'in-progress'}}),
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._pending_tasks

    def test_on_tool_executed_handles_missing_agent_id(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'tool_name': 'kanban_update_status',
            'tool_result': {'task': {'id': 'task-1', 'status': 'in-progress'}},
        }
        # Should not raise
        self._handler.on_tool_executed(event, sdk=None)
        # siwa's task should remain (no agent_id in event)
        assert 'siwa' in self._handler._pending_tasks

    # \u2500\u2500 on_tool_executed: kanban_update_task (successor tool) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    def test_kanban_update_task_in_progress_clears_pending(self):
        self._handler._pending_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_task',
            'tool_result': {'task': {'id': 'task-1', 'status': 'in-progress'}},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._pending_tasks
        assert self._handler._active_tasks.get('siwa') == 'task-1'

    def test_kanban_update_task_done_clears_active(self):
        self._handler._active_tasks['siwa'] = 'task-1'
        event = {
            'agent_id': 'siwa',
            'tool_name': 'kanban_update_task',
            'tool_result': {'task': {'id': 'task-1', 'status': 'done'}},
        }
        self._handler.on_tool_executed(event, sdk=None)
        assert 'siwa' not in self._handler._active_tasks

    # ── Self-healing guard ───────────────────────────────────────────────────

    def test_guard_self_heals_when_task_is_done_on_disk(self):
        import unittest.mock as mock
        self._handler._pending_tasks['siwa'] = 'task-stale'
        with mock.patch('plugins.kanban.db.kanban_db') as mock_db:
            mock_db.get.return_value = {'id': 'task-stale', 'status': 'done'}
            result = self._handler._tool_guard('siwa', 'bash', {})
        assert result is None
        assert 'siwa' not in self._handler._pending_tasks

    def test_guard_self_heals_when_task_is_in_progress_on_disk(self):
        import unittest.mock as mock
        self._handler._pending_tasks['siwa'] = 'task-stale'
        with mock.patch('plugins.kanban.db.kanban_db') as mock_db:
            mock_db.get.return_value = {'id': 'task-stale', 'status': 'in-progress'}
            result = self._handler._tool_guard('siwa', 'bash', {})
        assert result is None
        assert 'siwa' not in self._handler._pending_tasks

    def test_guard_self_heals_when_task_not_found_on_disk(self):
        import unittest.mock as mock
        self._handler._pending_tasks['siwa'] = 'task-gone'
        with mock.patch('plugins.kanban.db.kanban_db') as mock_db:
            mock_db.get.return_value = None
            result = self._handler._tool_guard('siwa', 'bash', {})
        assert result is None
        assert 'siwa' not in self._handler._pending_tasks

    def test_guard_still_blocks_when_task_is_todo_on_disk(self):
        """Reuses _guard() helper which already mocks _load_tasks with todo status."""
        self._handler._pending_tasks['siwa'] = 'task-real'
        result = self._guard('siwa', 'bash', task_status='todo')
        assert result is not None
        assert result['block'] is True

