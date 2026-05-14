"""
Unit tests for agent messaging tools.

Tests _exec_send_agent_message, _exec_escalate_to_user,
_exec_resolve_agent_approval, _on_final_answer, and _check_rate_limit.
All external dependencies (db, notifier, approval_registry, event_stream)
are mocked via unittest.mock.
"""
import time
import unittest
import unittest.mock as mock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# -------------------------------------------------------
# Module-level mock objects (created here so helpers below can reference them,
# but NOT injected into sys.modules until setup_module runs).
# -------------------------------------------------------
_mock_db = mock.MagicMock()
_mock_db.get_agent = mock.MagicMock()
_mock_db.get_latest_human_session = mock.MagicMock()
_mock_db.get_session_messages = mock.MagicMock()

_mock_notifier = mock.MagicMock()
_mock_notifier.notify_agent = mock.MagicMock()

_mock_approval = mock.MagicMock()
_mock_approval.approval_registry = mock.MagicMock()

# Keys whose original sys.modules values are saved in setup_module.
_STUB_KEYS = [
    'models', 'models.db',
    'backend.agent_runtime',
    'backend.agent_runtime.notifier',
    'backend.agent_runtime.approval',
]
_saved_modules: dict = {}


def setup_module(module):
    """Install sys.modules stubs before any test in this file runs.

    Moved out of module scope so other test files collected earlier/later
    do not see these stubs during pytest collection.
    """
    import backend as _backend_pkg

    # Save originals (None means absent).
    for key in _STUB_KEYS:
        _saved_modules[key] = sys.modules.get(key)

    sys.modules['models.db'] = mock.MagicMock(db=_mock_db)
    sys.modules['models'] = mock.MagicMock()
    sys.modules['backend.agent_runtime.notifier'] = _mock_notifier
    sys.modules['backend.agent_runtime'] = mock.MagicMock()
    sys.modules['backend.agent_runtime.approval'] = _mock_approval

    # mock.patch traverses the real `backend` module via getattr, so we need
    # to expose the mocked submodules as attributes on the real package object.
    _backend_pkg.agent_runtime = sys.modules['backend.agent_runtime']
    _backend_pkg.agent_runtime.notifier = _mock_notifier
    _backend_pkg.agent_runtime.approval = _mock_approval


def teardown_module(module):
    """Restore sys.modules to pre-test state so stubs don't leak."""
    import backend as _backend_pkg

    for key, saved in _saved_modules.items():
        if saved is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved

    # Also remove backend.tools.agent_messaging so it can be re-imported
    # fresh by subsequent test files without our stubs cached inside it.
    sys.modules.pop('backend.tools.agent_messaging', None)

    # Restore backend.agent_runtime attribute if possible
    if 'backend.agent_runtime' in sys.modules:
        _backend_pkg.agent_runtime = sys.modules['backend.agent_runtime']
    elif hasattr(_backend_pkg, 'agent_runtime'):
        try:
            delattr(_backend_pkg, 'agent_runtime')
        except AttributeError:
            pass


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _make_agent_context(agent_id='agent_a', agent_name='Agent A',
                        user_id='user_123', depth=0):
    return {
        'id': agent_id,
        'name': agent_name,
        'user_id': user_id,
        'agent_message_depth': depth,
    }


def _make_target_agent(agent_id='agent_b', name='Agent B',
                       enabled=True, is_super=False):
    return {
        'id': agent_id,
        'name': name,
        'enabled': enabled,
        'is_super': is_super,
    }


# -------------------------------------------------------
# _check_rate_limit — no external deps, test directly
# -------------------------------------------------------

class TestCheckRateLimit(unittest.TestCase):
    """Test the internal rate limiter."""

    def setUp(self):
        from backend.tools.agent_messaging import _rate_limit_buckets, _check_rate_limit
        _rate_limit_buckets.clear()
        self._check_rate_limit = _check_rate_limit

    def test_allows_first_ten(self):
        """First 10 messages from same sender-target pair are allowed."""
        for i in range(10):
            self.assertTrue(
                self._check_rate_limit('agent_a', 'agent_b'),
                f"Message {i} should be allowed",
            )

    def test_blocks_eleventh(self):
        """11th message within window is blocked."""
        for _ in range(10):
            self._check_rate_limit('agent_a', 'agent_b')
        self.assertFalse(self._check_rate_limit('agent_a', 'agent_b'))

    def test_different_pair_independent(self):
        """Rate limit is per (sender, target) pair."""
        # Fill up quota for A→B
        for _ in range(10):
            self._check_rate_limit('agent_a', 'agent_b')
        # A→B should be blocked now
        self.assertFalse(self._check_rate_limit('agent_a', 'agent_b'))
        # A→C should still work (different target)
        self.assertTrue(self._check_rate_limit('agent_a', 'agent_c'))
        # C→B should still work (different sender)
        self.assertTrue(self._check_rate_limit('agent_c', 'agent_b'))

    def test_prunes_old_entries(self):
        """Entries older than _RATE_LIMIT_WINDOW are pruned."""
        from backend.tools.agent_messaging import _rate_limit_buckets, _RATE_LIMIT_WINDOW

        # Insert 10 old timestamps
        old = time.time() - _RATE_LIMIT_WINDOW - 10
        _rate_limit_buckets[('agent_a', 'agent_b')] = [old] * 10

        # Next call should prune them and allow
        self.assertTrue(self._check_rate_limit('agent_a', 'agent_b'))


# -------------------------------------------------------
# _exec_send_agent_message
# -------------------------------------------------------

class TestExecSendAgentMessage(unittest.TestCase):
    """Test _exec_send_agent_message with mocked db and notifier."""

    def setUp(self):
        from backend.tools.agent_messaging import (
            _rate_limit_buckets, _global_rate_limit_buckets, _fanout_buckets,
        )
        _rate_limit_buckets.clear()
        _global_rate_limit_buckets.clear()
        _fanout_buckets.clear()

    def _call(self, args, agent_context=None):
        from backend.tools.agent_messaging import _exec_send_agent_message
        ctx = agent_context or _make_agent_context()
        return _exec_send_agent_message(args, ctx)

    def test_success(self):
        """Sending to a valid, enabled agent returns success + reply_to_id."""
        target = _make_target_agent()
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            result = self._call({
                'target_agent_id': 'agent_b',
                'message': 'Hello from A!',
            })
        self.assertTrue(result.get('success'))
        self.assertIn('reply_to_id', result)
        self.assertIn('Message sent', result.get('message', ''))
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        meta = call_kwargs.get('metadata', {})
        self.assertTrue(meta.get('agent_message'))
        self.assertEqual(meta.get('from_agent_id'), 'agent_a')
        self.assertEqual(meta.get('report_to_id'), 'user_123')

    def test_self_messaging_blocked(self):
        """Agent cannot message itself."""
        result = self._call(
            {'target_agent_id': 'agent_a', 'message': 'Hi me'},
            _make_agent_context(agent_id='agent_a'),
        )
        self.assertIn('error', result)
        self.assertIn('cannot send a message to itself', result['error'])

    def test_target_not_found(self):
        """Non-existent target returns error."""
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=None):
            result = self._call({
                'target_agent_id': 'ghost',
                'message': 'Hello?',
            })
        self.assertIn('error', result)
        self.assertIn('not found', result['error'])

    def test_target_disabled(self):
        """Disabled target returns error (unless super)."""
        target = _make_target_agent(enabled=False, is_super=False)
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target):
            result = self._call({
                'target_agent_id': 'agent_b',
                'message': 'Hello?',
            })
        self.assertIn('error', result)
        self.assertIn('disabled', result['error'])

    def test_target_super_always_allowed(self):
        """Super agent is allowed even if enabled=False."""
        target = _make_target_agent(enabled=False, is_super=True)
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent'):
            result = self._call({
                'target_agent_id': 'agent_b',
                'message': 'Hello super!',
            })
        self.assertTrue(result.get('success'))

    def test_empty_target_id(self):
        """Missing target_agent_id returns error."""
        result = self._call({'target_agent_id': '', 'message': 'Hi'})
        self.assertIn('error', result)
        self.assertIn('target_agent_id', result['error'])

    def test_empty_message(self):
        """Missing message returns error."""
        result = self._call({'target_agent_id': 'agent_b', 'message': '  '})
        self.assertIn('error', result)
        self.assertIn('message', result['error'])

    def test_rate_limit_exceeded(self):
        """11th message within window is blocked."""
        target = _make_target_agent()
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent'):
            for i in range(10):
                result = self._call({
                    'target_agent_id': 'agent_b',
                    'message': f'Msg {i}',
                })
                self.assertTrue(result.get('success'), f'Message {i} should succeed')

            result = self._call({
                'target_agent_id': 'agent_b',
                'message': 'Msg 11',
            })
        self.assertIn('error', result)
        self.assertIn('Rate limit', result['error'])

    def test_depth_limit(self):
        """Messages at max depth are blocked."""
        target = _make_target_agent()
        ctx = _make_agent_context(depth=3)  # _MAX_DEPTH = 3
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target):
            result = self._call({
                'target_agent_id': 'agent_b',
                'message': 'Deep msg',
            }, agent_context=ctx)
        self.assertIn('error', result)
        self.assertIn('depth', result['error'].lower())

    def test_reply_back_to_sender_blocked(self):
        """B cannot send_agent_message back to A when A is from_agent_id."""
        target = _make_target_agent(agent_id='agent_a', name='Agent A')
        ctx = {
            'id': 'agent_b',
            'name': 'Agent B',
            'user_id': '__agent__agent_a',
            'agent_message_depth': 1,
            'from_agent_id': 'agent_a',  # A delegated this task to B
        }
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target):
            result = self._call(
                {'target_agent_id': 'agent_a', 'message': 'Hey A, I have a question'},
                agent_context=ctx,
            )
        self.assertIn('error', result)
        self.assertIn('forwarded back', result['error'])

    def test_reply_back_blocked_does_not_call_notifier(self):
        """When reply-back is blocked, notify_agent must not be called."""
        target = _make_target_agent(agent_id='agent_a', name='Agent A')
        ctx = {
            'id': 'agent_b',
            'name': 'Agent B',
            'user_id': '__agent__agent_a',
            'agent_message_depth': 1,
            'from_agent_id': 'agent_a',
        }
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            self._call(
                {'target_agent_id': 'agent_a', 'message': 'Hey A'},
                agent_context=ctx,
            )
        mock_notify.assert_not_called()

    def test_send_to_third_party_allowed_when_from_agent_set(self):
        """B can still send to C even when A is from_agent_id (only reply-back is blocked)."""
        target_c = _make_target_agent(agent_id='agent_c', name='Agent C')
        ctx = {
            'id': 'agent_b',
            'name': 'Agent B',
            'user_id': '__agent__agent_a',
            'agent_message_depth': 1,
            'from_agent_id': 'agent_a',
        }
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target_c), \
             mock.patch('backend.agent_runtime.notifier.notify_agent'):
            result = self._call(
                {'target_agent_id': 'agent_c', 'message': 'Hey C, help needed'},
                agent_context=ctx,
            )
        self.assertTrue(result.get('success'))

    def test_no_from_agent_id_does_not_restrict_target(self):
        """Without from_agent_id in context, no reply-back restriction applies."""
        target = _make_target_agent(agent_id='agent_a', name='Agent A')
        ctx = _make_agent_context(agent_id='agent_b', user_id='user_xyz')
        # from_agent_id is NOT set — should be allowed
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent'):
            result = self._call(
                {'target_agent_id': 'agent_a', 'message': 'Direct msg to A'},
                agent_context=ctx,
            )
        self.assertTrue(result.get('success'))


# -------------------------------------------------------
# Metadata injection
# -------------------------------------------------------

class TestMetadataInjection(unittest.TestCase):
    """Verify metadata fields on successful send_agent_message calls."""

    def setUp(self):
        from backend.tools.agent_messaging import (
            _rate_limit_buckets, _global_rate_limit_buckets, _fanout_buckets,
        )
        _rate_limit_buckets.clear()
        _global_rate_limit_buckets.clear()
        _fanout_buckets.clear()

    def _call(self, args, agent_context=None):
        from backend.tools.agent_messaging import _exec_send_agent_message
        ctx = agent_context or _make_agent_context()
        return _exec_send_agent_message(args, ctx)

    def test_reply_to_id_is_unique(self):
        """Each call generates a unique reply_to_id."""
        target = _make_target_agent()
        ids = set()
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent'):
            for _ in range(5):
                result = self._call({'target_agent_id': 'agent_b', 'message': 'Hi'})
                ids.add(result['reply_to_id'])
        self.assertEqual(len(ids), 5, "Each call must produce a unique reply_to_id")

    def test_report_to_id_from_context(self):
        """report_to_id is taken from agent_context['user_id']."""
        target = _make_target_agent()
        ctx = _make_agent_context(user_id='custom_user_42')
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            self._call({'target_agent_id': 'agent_b', 'message': 'Hi'}, agent_context=ctx)
        meta = mock_notify.call_args.kwargs.get('metadata', {})
        self.assertEqual(meta.get('report_to_id'), 'custom_user_42')

    def test_depth_incremented(self):
        """agent_message_depth is incremented by 1 in metadata."""
        target = _make_target_agent()
        ctx = _make_agent_context(depth=2)
        with mock.patch('backend.tools.agent_messaging.db.get_agent', return_value=target), \
             mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            self._call({'target_agent_id': 'agent_b', 'message': 'Hi'}, agent_context=ctx)
        meta = mock_notify.call_args.kwargs.get('metadata', {})
        self.assertEqual(meta.get('agent_message_depth'), 3)


# -------------------------------------------------------
# _exec_escalate_to_user
# -------------------------------------------------------

class TestExecEscalateToUser(unittest.TestCase):
    """Test _exec_escalate_to_user with mocked db and notifier."""

    def _call(self, args, agent_context=None):
        from backend.tools.agent_messaging import _exec_escalate_to_user
        ctx = agent_context or _make_agent_context(
            user_id='__agent__agent_a'  # inter-agent session
        )
        return _exec_escalate_to_user(args, ctx)

    def test_success(self):
        """Escalate in inter-agent session with valid human session."""
        human_session = {'external_user_id': 'user_123', 'channel_id': 'ch1'}
        with mock.patch('backend.tools.agent_messaging.db.get_latest_human_session',
                        return_value=human_session), \
             mock.patch('backend.tools.agent_messaging.db.get_web_fallback_session',
                        return_value=None), \
             mock.patch('backend.agent_runtime.notifier.notify_agent',
                       return_value={'success': True}) as mock_notify:
            result = self._call({'message': 'User, I need your approval.'})
        self.assertTrue(result.get('success'))
        self.assertIn('forwarded', result.get('message', ''))
        mock_notify.assert_called_once()
        self.assertEqual(
            mock_notify.call_args.kwargs.get('external_user_id'),
            'user_123',
        )

    def test_already_in_user_session(self):
        """Block escalate when not in inter-agent session."""
        ctx = _make_agent_context(user_id='user_123')  # normal user session
        result = self._call({'message': 'Hello?'}, agent_context=ctx)
        self.assertIn('error', result)
        self.assertIn('user session', result['error'])

    def test_no_human_session(self):
        """Block escalate when no human session exists."""
        with mock.patch('backend.tools.agent_messaging.db.get_latest_human_session',
                        return_value=None):
            result = self._call({'message': 'Hello?'})
        self.assertIn('error', result)
        self.assertIn('No active human', result['error'])


# -------------------------------------------------------
# _exec_resolve_agent_approval
# -------------------------------------------------------

class TestExecResolveAgentApproval(unittest.TestCase):
    """Test _exec_resolve_agent_approval with mocked approval_registry."""

    def _call(self, args, agent_context=None):
        from backend.tools.agent_messaging import _exec_resolve_agent_approval
        ctx = agent_context or _make_agent_context()
        return _exec_resolve_agent_approval(args, ctx)

    def test_approve_success(self):
        """Approve a pending approval returns success."""
        mock_pa = mock.MagicMock()
        mock_pa.decision = None
        mock_pa.session_id = 'sess_001'
        with mock.patch(
            'backend.agent_runtime.approval.approval_registry.get',
            return_value=mock_pa,
        ), mock.patch(
            'backend.agent_runtime.approval.approval_registry.resolve',
            return_value=True,
        ):
            result = self._call({
                'approval_id': 'apr_001',
                'decision': 'approve',
            })
        self.assertTrue(result.get('success'))
        self.assertEqual(result.get('decision'), 'approve')
        self.assertIn('approved', result.get('message', ''))

    def test_reject_success(self):
        """Reject a pending approval returns success."""
        mock_pa = mock.MagicMock()
        mock_pa.decision = None
        mock_pa.session_id = 'sess_002'
        with mock.patch(
            'backend.agent_runtime.approval.approval_registry.get',
            return_value=mock_pa,
        ), mock.patch(
            'backend.agent_runtime.approval.approval_registry.resolve',
            return_value=True,
        ):
            result = self._call({
                'approval_id': 'apr_002',
                'decision': 'reject',
            })
        self.assertTrue(result.get('success'))
        self.assertEqual(result.get('decision'), 'reject')

    def test_already_resolved(self):
        """Already resolved approval returns error."""
        mock_pa = mock.MagicMock()
        mock_pa.decision = 'approve'  # already resolved
        with mock.patch(
            'backend.agent_runtime.approval.approval_registry.get',
            return_value=mock_pa,
        ):
            result = self._call({
                'approval_id': 'apr_003',
                'decision': 'reject',
            })
        self.assertIn('error', result)
        self.assertIn('already resolved', result['error'])

    def test_not_found(self):
        """Non-existent/expired approval returns error."""
        with mock.patch(
            'backend.agent_runtime.approval.approval_registry.get',
            return_value=None,
        ):
            result = self._call({
                'approval_id': 'apr_ghost',
                'decision': 'approve',
            })
        self.assertIn('error', result)
        self.assertIn('not found', result['error'])

    def test_could_not_resolve(self):
        """Resolve returns False (just expired) returns error."""
        mock_pa = mock.MagicMock()
        mock_pa.decision = None
        with mock.patch(
            'backend.agent_runtime.approval.approval_registry.get',
            return_value=mock_pa,
        ), mock.patch(
            'backend.agent_runtime.approval.approval_registry.resolve',
            return_value=False,
        ):
            result = self._call({
                'approval_id': 'apr_004',
                'decision': 'approve',
            })
        self.assertIn('error', result)
        self.assertIn('Could not resolve', result['error'])

    def test_empty_approval_id(self):
        """Missing approval_id returns error."""
        result = self._call({'approval_id': '', 'decision': 'approve'})
        self.assertIn('error', result)
        self.assertIn('approval_id', result['error'])

    def test_invalid_decision(self):
        """Invalid decision value returns error."""
        result = self._call({'approval_id': 'apr_001', 'decision': 'maybe'})
        self.assertIn('error', result)
        self.assertIn('decision', result['error'])


# -------------------------------------------------------
# _on_final_answer
# -------------------------------------------------------

class TestOnFinalAnswer(unittest.TestCase):
    """Test _on_final_answer auto-forward with mocked db and notifier."""

    def _call(self, data):
        from backend.tools.agent_messaging import _on_final_answer
        return _on_final_answer(data)

    def _build_data(self, external_user_id='__agent__agent_a',
                    agent_id='agent_b', session_id='sess_001',
                    answer='Hello back!', tool_trace=None,
                    message_metadata=None):
        return {
            'external_user_id': external_user_id,
            'agent_id': agent_id,
            'session_id': session_id,
            'answer': answer,
            'tool_trace': tool_trace,
            '_test_metadata': message_metadata,  # used below in mock
        }

    def test_non_inter_agent_skips(self):
        """Normal user session — no forwarding."""
        with mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            self._call(self._build_data(external_user_id='user_123'))
        mock_notify.assert_not_called()

    def test_no_report_to_id_skips(self):
        """Metadata without report_to_id — no forwarding."""
        messages = [
            {'metadata': {'from_agent_id': 'agent_a'}},  # no report_to_id
        ]
        with mock.patch(
            'backend.tools.agent_messaging.db.get_session_messages',
            return_value=messages,
        ), mock.patch('backend.agent_runtime.notifier.notify_agent') as mock_notify:
            self._call(self._build_data())
        mock_notify.assert_not_called()

    def test_inter_agent_forwards_reply(self):
        """Inter-agent session with valid metadata forwards reply to A."""
        messages = [
            {'metadata': {
                'from_agent_id': 'agent_a',
                'report_to_id': 'user_123',
            }},
        ]
        target_agent = _make_target_agent(agent_id='agent_b', name='Agent B')
        with mock.patch(
            'backend.tools.agent_messaging.db.get_session_messages',
            return_value=messages,
        ), mock.patch(
            'backend.tools.agent_messaging.db.get_agent',
            return_value=target_agent,
        ), mock.patch(
            'backend.agent_runtime.notifier.notify_agent',
        ) as mock_notify:
            self._call(self._build_data(
                answer='Hello from B!',
            ))
        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        self.assertEqual(kwargs.get('agent_id'), 'agent_a')
        self.assertEqual(kwargs.get('external_user_id'), 'user_123')
        self.assertTrue(kwargs.get('trigger_llm'))

    def test_depth_preserved_in_forwarded_metadata(self):
        """_on_final_answer preserves agent_message_depth from original message in forwarded metadata."""
        messages = [
            {'metadata': {
                'from_agent_id': 'agent_a',
                'report_to_id': 'user_123',
                'agent_message_depth': 2,  # depth A→B was 2
            }},
        ]
        target_agent = _make_target_agent(agent_id='agent_b', name='Agent B')
        with mock.patch(
            'backend.tools.agent_messaging.db.get_session_messages',
            return_value=messages,
        ), mock.patch(
            'backend.tools.agent_messaging.db.get_agent',
            return_value=target_agent,
        ), mock.patch(
            'backend.agent_runtime.notifier.notify_agent',
        ) as mock_notify:
            self._call(self._build_data(answer='Task done!'))
        mock_notify.assert_called_once()
        forwarded_meta = mock_notify.call_args.kwargs.get('metadata', {})
        self.assertEqual(
            forwarded_meta.get('agent_message_depth'), 2,
            "Forwarded metadata must carry original depth so A's context is correct",
        )

    def test_depth_defaults_to_zero_when_missing(self):
        """_on_final_answer defaults agent_message_depth to 0 if not in original metadata."""
        messages = [
            {'metadata': {
                'from_agent_id': 'agent_a',
                'report_to_id': 'user_123',
                # agent_message_depth intentionally absent
            }},
        ]
        target_agent = _make_target_agent(agent_id='agent_b', name='Agent B')
        with mock.patch(
            'backend.tools.agent_messaging.db.get_session_messages',
            return_value=messages,
        ), mock.patch(
            'backend.tools.agent_messaging.db.get_agent',
            return_value=target_agent,
        ), mock.patch(
            'backend.agent_runtime.notifier.notify_agent',
        ) as mock_notify:
            self._call(self._build_data(answer='Done!'))
        mock_notify.assert_called_once()
        forwarded_meta = mock_notify.call_args.kwargs.get('metadata', {})
        self.assertEqual(forwarded_meta.get('agent_message_depth'), 0)


# -------------------------------------------------------
# _check_global_rate_limit
# -------------------------------------------------------

class TestCheckGlobalRateLimit(unittest.TestCase):
    """Test the global rate limiter (across all targets)."""

    def setUp(self):
        from backend.tools.agent_messaging import (
            _global_rate_limit_buckets,
            _check_global_rate_limit,
        )
        _global_rate_limit_buckets.clear()
        self._check_global_rate_limit = _check_global_rate_limit

    def test_allows_first_30(self):
        """First 30 messages from sender are allowed."""
        for i in range(30):
            self.assertTrue(
                self._check_global_rate_limit('agent_a'),
                f"Message {i} should be allowed",
            )

    def test_blocks_31st(self):
        """31st message within window is blocked."""
        for _ in range(30):
            self._check_global_rate_limit('agent_a')
        self.assertFalse(self._check_global_rate_limit('agent_a'))

    def test_prunes_old_entries(self):
        """Entries older than window are pruned from bucket."""
        from backend.tools.agent_messaging import (
            _global_rate_limit_buckets,
            _GLOBAL_RATE_LIMIT_WINDOW,
        )
        # Fill with 30 old timestamps
        old = time.time() - _GLOBAL_RATE_LIMIT_WINDOW - 10
        _global_rate_limit_buckets['agent_a'] = [old] * 30
        # Next call should prune and allow
        self.assertTrue(self._check_global_rate_limit('agent_a'))

    def test_different_senders_independent(self):
        """Global rate limit is per sender, not global across all."""
        # Fill up agent_a
        for _ in range(30):
            self._check_global_rate_limit('agent_a')
        # agent_a blocked
        self.assertFalse(self._check_global_rate_limit('agent_a'))
        # agent_b should still work
        self.assertTrue(self._check_global_rate_limit('agent_b'))


# -------------------------------------------------------
# _check_fanout_limit
# -------------------------------------------------------

class TestCheckFanoutLimit(unittest.TestCase):
    """Test the fan-out limiter (unique targets per turn window)."""

    def setUp(self):
        from backend.tools.agent_messaging import (
            _fanout_buckets,
            _check_fanout_limit,
        )
        _fanout_buckets.clear()
        self._check_fanout_limit = _check_fanout_limit

    def test_allows_up_to_5_unique_targets(self):
        """Up to 5 unique targets in the window are allowed."""
        for i in range(5):
            target = f'agent_{i}'
            self.assertTrue(
                self._check_fanout_limit('agent_a', target),
                f"Target {target} should be allowed",
            )

    def test_blocks_6th_unique_target(self):
        """6th unique target within the window is blocked."""
        for i in range(5):
            self._check_fanout_limit('agent_a', f'agent_{i}')
        self.assertFalse(self._check_fanout_limit('agent_a', 'agent_5'))

    def test_prunes_old_entries(self):
        """Targets older than window are pruned, freeing up slots."""
        from backend.tools.agent_messaging import (
            _fanout_buckets,
            _FANOUT_WINDOW,
        )
        # Fill with 5 old entries (past window)
        old = time.time() - _FANOUT_WINDOW - 10
        _fanout_buckets['agent_a'] = [(old, f'agent_{i}') for i in range(5)]
        # Next 5 unique targets should all be allowed since old ones pruned
        for i in range(5):
            self.assertTrue(
                self._check_fanout_limit('agent_a', f'new_target_{i}'),
                f"new_target_{i} should be allowed after prune",
            )

    def test_same_target_twice_counts_once(self):
        """Messaging the same target twice only counts as 1 unique target."""
        # Send to 4 unique targets
        for i in range(4):
            self._check_fanout_limit('agent_a', f'agent_{i}')
        # Send to same target again — should still count as 1 unique
        self.assertTrue(self._check_fanout_limit('agent_a', 'agent_0'))
        # Now send to 5th unique target — should be allowed (only 5 unique so far)
        self.assertTrue(self._check_fanout_limit('agent_a', 'agent_new'))
        # But 6th unique target — blocked
        self.assertFalse(self._check_fanout_limit('agent_a', 'agent_6th'))

    def test_different_senders_independent(self):
        """Fan-out limit is per sender."""
        # Fill up agent_a
        for i in range(5):
            self._check_fanout_limit('agent_a', f'agent_a_target_{i}')
        # agent_a blocked for new targets
        self.assertFalse(self._check_fanout_limit('agent_a', 'agent_a_target_new'))
        # agent_b still has clean slate
        self.assertTrue(self._check_fanout_limit('agent_b', 'agent_b_target_1'))


if __name__ == '__main__':
    unittest.main()
