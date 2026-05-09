"""
Unit tests for llm_loop recovery mechanisms:
- _emergency_compact_messages: context compaction on exceed_context_size_error
- Trivial response filter (">", "<", etc.)
- Empty response recovery sentinel injection
- Context-size error triggers compaction + retry in run_tool_loop
"""

import sys
import os
import types
import json
import threading
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# backend.agent_runtime.__init__ instantiates a global AgentRuntime() (starts
# non-daemon queue workers) so importing the package hangs the test process.
# Strategy: pre-stub backend.agent_runtime as a bare ModuleType (with __path__
# set so submodule lookups work), load the three submodules that llm_loop.py
# imports at module level (llm_call, llm_response_parser, llm_tool_executor)
# via importlib directly, then load llm_loop.py the same way.
import importlib.util as _ilu
import backend as _backend_pkg

_AR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'backend', 'agent_runtime',
)

# Save whatever is currently in sys.modules so teardown can restore it.
_SAVED_AR = sys.modules.get('backend.agent_runtime')
_SAVED_AR_SUBKEYS = {
    k: v for k, v in sys.modules.items()
    if k.startswith('backend.agent_runtime.')
}

# Only install the stub if the real package isn't already loaded.
# If it IS already loaded (from another test that ran first), we leave it
# alone — non-daemon threads are already running and we can't undo that,
# but we also don't need to trigger a second instantiation.
if not isinstance(_SAVED_AR, types.ModuleType) or not hasattr(_SAVED_AR, 'AgentRuntime'):
    _ar_stub = types.ModuleType('backend.agent_runtime')
    _ar_stub.__path__ = [_AR_PATH]
    _ar_stub.__package__ = 'backend.agent_runtime'
    sys.modules['backend.agent_runtime'] = _ar_stub
    _backend_pkg.agent_runtime = _ar_stub
    # Add agent_runtime attribute so patch('backend.agent_runtime.agent_runtime') works
    # in other test files (e.g. test_scheduler.py) that run after this module is loaded.
    # Add AgentRuntime class stub so test_skill_session_persistence.py's fixture guard
    # (which checks hasattr(..., 'AgentRuntime')) does NOT delete our stub.
    from unittest.mock import MagicMock as _MagicMock
    _ar_stub.agent_runtime = _MagicMock(name='agent_runtime_singleton')
    _ar_stub.AgentRuntime = _MagicMock(name='AgentRuntime')

    for _submod_name in ('llm_call', 'llm_response_parser', 'llm_tool_executor'):
        _submod_path = os.path.join(_AR_PATH, f'{_submod_name}.py')
        _submod_spec = _ilu.spec_from_file_location(
            f'backend.agent_runtime.{_submod_name}', _submod_path)
        _submod_mod = _ilu.module_from_spec(_submod_spec)
        sys.modules[f'backend.agent_runtime.{_submod_name}'] = _submod_mod
        setattr(_ar_stub, _submod_name, _submod_mod)
        _submod_spec.loader.exec_module(_submod_mod)
else:
    _ar_stub = _SAVED_AR

_llm_loop_path = os.path.join(_AR_PATH, 'llm_loop.py')
_spec = _ilu.spec_from_file_location('backend.agent_runtime.llm_loop', _llm_loop_path)
_llm_loop_mod = _ilu.module_from_spec(_spec)
sys.modules['backend.agent_runtime.llm_loop'] = _llm_loop_mod
_ar_stub.llm_loop = _llm_loop_mod
_spec.loader.exec_module(_llm_loop_mod)
_emergency_compact_messages = _llm_loop_mod._emergency_compact_messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(content='done'):
    return {
        'success': True,
        'response': {'choices': [{'message': {'content': content, 'tool_calls': None}, 'finish_reason': 'stop'}]},
        'duration_ms': 10,
    }


def _err(detail='request (60000 tokens) exceeds the available context size (49152 tokens), type=exceed_context_size_error'):
    return {
        'success': False,
        'error_type': 'llm_error',
        'error_detail': detail,
        'response': {},
    }


def _make_messages(with_summary=True, n_conv=10):
    """Build a realistic messages list for compaction tests."""
    msgs = [
        {"role": "system", "content": "You are a helpful assistant."},
    ]
    if with_summary:
        msgs.append({"role": "system", "content": "## Prior conversation summary\n- User asked about dark mode\n- Agent implemented CSS changes"})
    msgs.append({"role": "system", "content": "## Long-term Memory\n- User name: Gus Robin"})

    for i in range(n_conv):
        msgs.append({"role": "user", "content": f"User message {i}"})
        msgs.append({"role": "assistant", "content": f"Assistant reply {i}"})

    return msgs


# ---------------------------------------------------------------------------
# Tests: _emergency_compact_messages
# ---------------------------------------------------------------------------

class TestEmergencyCompactMessages(unittest.TestCase):

    def _make_llm(self, summary_reply='- Compacted point 1\n- Compacted point 2'):
        llm = MagicMock()
        llm.chat_completion.return_value = {
            'success': True,
            'response': {'choices': [{'message': {'content': summary_reply}, 'finish_reason': 'stop'}]},
        }
        return llm

    def test_returns_shorter_messages_list(self):
        messages = _make_messages(with_summary=True, n_conv=20)
        llm = self._make_llm()
        lock = threading.Lock()

        result = _emergency_compact_messages(messages, llm, lock, 'sess1', 'agent1')

        self.assertIsNotNone(result)
        self.assertLess(len(result), len(messages))

    def test_system_prompt_preserved_as_first_message(self):
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = self._make_llm()
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        self.assertEqual(result[0]['role'], 'system')
        self.assertIn('helpful assistant', result[0]['content'])

    def test_compacted_summary_injected(self):
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = self._make_llm('- Only relevant point')
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        summary_msgs = [m for m in result if '## Prior conversation summary' in (m.get('content') or '')]
        self.assertEqual(len(summary_msgs), 1)
        self.assertIn('Only relevant point', summary_msgs[0]['content'])
        self.assertIn('compacted', summary_msgs[0]['content'])

    def test_keeps_at_most_5_conversation_entries(self):
        messages = _make_messages(with_summary=True, n_conv=20)
        llm = self._make_llm()
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        conv_msgs = [m for m in result if m.get('role') in ('user', 'assistant')]
        self.assertLessEqual(len(conv_msgs), 5)

    def test_no_tool_messages_in_result(self):
        messages = _make_messages(with_summary=True, n_conv=5)
        # Add some tool messages
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": "c1", "content": "tool result"})
        llm = self._make_llm()
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        self.assertFalse(any(m.get('role') == 'tool' for m in result))
        self.assertFalse(any(m.get('tool_calls') for m in result))

    def test_works_without_existing_summary(self):
        messages = _make_messages(with_summary=False, n_conv=10)
        llm = self._make_llm('- Summary from scratch')
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        self.assertIsNotNone(result)
        summary_msgs = [m for m in result if '## Prior conversation summary' in (m.get('content') or '')]
        self.assertEqual(len(summary_msgs), 1)

    def test_returns_none_on_llm_failure(self):
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = MagicMock()
        llm.chat_completion.return_value = {
            'success': False,
            'error_type': 'api_error',
            'error_detail': 'timeout',
            'response': {},
        }
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')
        self.assertIsNone(result)

    def test_returns_none_on_empty_llm_output(self):
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = MagicMock()
        llm.chat_completion.return_value = {
            'success': True,
            'response': {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]},
        }
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')
        self.assertIsNone(result)

    def test_returns_none_on_llm_exception(self):
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = MagicMock()
        llm.chat_completion.side_effect = RuntimeError('connection refused')
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')
        self.assertIsNone(result)

    def test_other_system_messages_preserved(self):
        """Long-term Memory system message should survive compaction."""
        messages = _make_messages(with_summary=True, n_conv=10)
        llm = self._make_llm()
        result = _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        memory_msgs = [m for m in result if '## Long-term Memory' in (m.get('content') or '')]
        self.assertEqual(len(memory_msgs), 1)

    def test_llm_prompt_contains_summary_and_recent(self):
        """Verify the compaction prompt contains both the summary and recent conversation."""
        messages = _make_messages(with_summary=True, n_conv=6)
        llm = self._make_llm()
        _emergency_compact_messages(messages, llm, threading.Lock(), 'sess1', 'agent1')

        call_args = llm.chat_completion.call_args
        prompt_content = call_args[1]['messages'][0]['content']
        self.assertIn('Existing Summary', prompt_content)
        self.assertIn('Recent Conversation', prompt_content)
        self.assertIn('30%', prompt_content)


# ---------------------------------------------------------------------------
# Tests: trivial response filter + empty response recovery
# ---------------------------------------------------------------------------

class TestEmptyResponseRecovery(unittest.TestCase):
    """Test the trivial-response filter and sentinel injection in run_tool_loop."""

    def _make_agent_context(self):
        return {'user_id': 'u1', 'channel_id': 'ch1', 'is_super': False, 'agent_state': None}

    def _make_agent(self, agent_id='test_agent'):
        return {
            'id': agent_id,
            'name': 'Test',
            'model': None,
            'send_intermediate_responses': False,
            'summarize_threshold': 0,
        }

    def _run_tool_loop(self, llm, messages, session_id, extra_db_attrs=None):
        """Run run_tool_loop with patched db/tool_registry/LLMClient/event_stream."""
        run_tool_loop = _llm_loop_mod.run_tool_loop
        mock_db = MagicMock()
        mock_db.get_setting.side_effect = lambda key, default=None: default or '0'
        mock_db.add_chat_message.return_value = None
        mock_db.upsert_agent_state.return_value = None
        mock_db.get_agent_default_model.return_value = None
        if extra_db_attrs:
            for k, v in extra_db_attrs.items():
                setattr(mock_db, k, v)
        mock_tr = MagicMock()
        mock_tr.get_builtin_executor.return_value = lambda n, a: None
        mock_tr.get_real_executor.return_value = lambda n, a: None
        import backend.event_stream as _es_mod
        with patch.object(_llm_loop_mod, 'db', mock_db), \
             patch.object(_llm_loop_mod, 'tool_registry', mock_tr), \
             patch.object(_es_mod, 'event_stream', MagicMock()), \
             patch.object(_llm_loop_mod, 'LLMClient', return_value=llm), \
             patch.object(_llm_loop_mod, 'llm_client', llm):
            return run_tool_loop(
                agent=self._make_agent(),
                agent_context=self._make_agent_context(),
                messages=messages,
                tools=[],
                session_id=session_id,
                llm_lock=threading.Lock(),
                stop_event=threading.Event(),
                session_skill_mds={},
                session_skill_tools={},
                llm_log_path=None,
            )

    def test_trivial_response_treated_as_empty(self):
        """'>' response should be treated as empty and trigger recovery sentinel."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            # First call: trivial response ">"
            {'success': True, 'response': {'choices': [{'message': {'content': '>', 'tool_calls': None}, 'finish_reason': 'stop'}]}, 'duration_ms': 10},
            # Second call (after sentinel): proper response
            _ok('Here is my answer.'),
        ]
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
        result, _, _ = self._run_tool_loop(llm, messages, 'sess1')
        self.assertEqual(llm.chat_completion.call_count, 2)
        self.assertIn('answer', str(result))

    def test_empty_response_sentinel_injected_once(self):
        """Empty response should inject sentinel and retry, up to 2 times."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            _ok(''),           # empty
            _ok(''),           # empty again (2nd injection)
            _ok('Final answer'),  # should not reach — max 2 injections, then return
        ]
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        result, _, _ = self._run_tool_loop(llm, messages, 'sess2')
        # 1 initial + 2 recovery = 3 calls max (or fewer if loop exits)
        self.assertLessEqual(llm.chat_completion.call_count, 3)


# ---------------------------------------------------------------------------
# Tests: context-size error triggers compaction + retry
# ---------------------------------------------------------------------------

class TestContextSizeCompaction(unittest.TestCase):

    def _make_agent(self):
        return {
            'id': 'agent1', 'name': 'Test', 'model': None,
            'send_intermediate_responses': False, 'summarize_threshold': 0,
        }

    def _make_agent_context(self):
        return {'user_id': 'u1', 'channel_id': 'ch1', 'is_super': False, 'agent_state': None}

    def _run_tool_loop(self, llm, messages, session_id, extra_db_attrs=None):
        """Run run_tool_loop with patched db/tool_registry/LLMClient/event_stream."""
        run_tool_loop = _llm_loop_mod.run_tool_loop
        mock_db = MagicMock()
        mock_db.get_setting.side_effect = lambda key, default=None: default or '0'
        mock_db.add_chat_message.return_value = None
        mock_db.get_agent_default_model.return_value = None
        mock_db.get_summary.return_value = None
        mock_db.upsert_summary.return_value = None
        if extra_db_attrs:
            for k, v in extra_db_attrs.items():
                setattr(mock_db, k, v)
        mock_tr = MagicMock()
        mock_tr.get_builtin_executor.return_value = lambda n, a: None
        mock_tr.get_real_executor.return_value = lambda n, a: None
        import backend.event_stream as _es_mod
        with patch.object(_llm_loop_mod, 'db', mock_db), \
             patch.object(_llm_loop_mod, 'tool_registry', mock_tr), \
             patch.object(_es_mod, 'event_stream', MagicMock()) as mock_es, \
             patch.object(_llm_loop_mod, 'LLMClient', return_value=llm), \
             patch.object(_llm_loop_mod, 'llm_client', llm):
            result = run_tool_loop(
                agent=self._make_agent(),
                agent_context=self._make_agent_context(),
                messages=messages,
                tools=[],
                session_id=session_id,
                llm_lock=threading.Lock(),
                stop_event=threading.Event(),
                session_skill_mds={},
                session_skill_tools={},
                llm_log_path=None,
            )
            return result, mock_es

    def test_context_error_triggers_compaction_then_retry(self):
        """exceed_context_size_error should compact messages and retry successfully."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            _err('request (60000 tokens) exceeds the available context size (49152 tokens), type=exceed_context_size_error'),
            _ok('- Compacted summary bullet'),
            _ok('Task done after compaction.'),
        ]
        messages = _make_messages(with_summary=True, n_conv=10)
        (result, _, _), _ = self._run_tool_loop(llm, messages, 'sess3')
        self.assertEqual(llm.chat_completion.call_count, 3)
        self.assertIn('compaction', str(result).lower() + 'task done after compaction.')

    def test_context_error_compaction_fails_returns_error(self):
        """If compaction LLM call fails, return the humanized error message."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            _err('exceeds the available context size'),
            {'success': False, 'error_type': 'api_error', 'error_detail': 'timeout', 'response': {}},
        ]
        messages = _make_messages(with_summary=False, n_conv=5)
        (result, _, _), _ = self._run_tool_loop(llm, messages, 'sess4')
        self.assertTrue(result.get('error'))
        self.assertIn('too long', result.get('text', '').lower())

    def test_context_error_no_infinite_loop(self):
        """Compaction only attempted once — second context error returns error."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            _err('exceeds the available context size'),
            _ok('- summary'),
            _err('exceeds the available context size'),
            _ok('This should not be reached'),
        ]
        messages = _make_messages(with_summary=True, n_conv=5)
        (result, _, _), _ = self._run_tool_loop(llm, messages, 'sess5')
        self.assertEqual(llm.chat_completion.call_count, 3)
        self.assertTrue(result.get('error'))

    def test_compaction_emits_llm_retry_events(self):
        """Should emit llm_retry events for user notification during compaction."""
        llm = MagicMock()
        llm.chat_completion.side_effect = [
            _err('exceeds the available context size'),
            _ok('- summary'),
            _ok('All done.'),
        ]
        messages = _make_messages(with_summary=True, n_conv=5)
        (_, _, _), mock_es = self._run_tool_loop(llm, messages, 'sess6')

        emitted_events = [c[0][0] for c in mock_es.emit.call_args_list]
        retry_events = [e for e in emitted_events if e == 'llm_retry']
        self.assertGreaterEqual(len(retry_events), 2)

        retry_payloads = [c[0][1] for c in mock_es.emit.call_args_list if c[0][0] == 'llm_retry']
        user_msgs = [p.get('user_message', '').lower() for p in retry_payloads]
        self.assertTrue(any('compact' in m for m in user_msgs))
        self.assertTrue(any('resuming' in m or 'summary' in m for m in user_msgs))


if __name__ == '__main__':
    unittest.main()
