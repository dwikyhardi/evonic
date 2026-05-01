"""Tests for TelegramNotifier: message formatting, progress bar, API calls."""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


class TestProgressBar(unittest.TestCase):
    def test_0_percent(self):
        bar = sup._progress_bar(0, 6)
        self.assertIn(sup.EMPTY * sup.BAR_WIDTH, bar)
        self.assertIn('0%', bar)

    def test_50_percent(self):
        bar = sup._progress_bar(3, 6)
        filled = sup.FILLED * (sup.BAR_WIDTH // 2)
        self.assertIn(filled, bar)
        self.assertIn('50%', bar)

    def test_100_percent(self):
        bar = sup._progress_bar(6, 6)
        self.assertIn(sup.FILLED * sup.BAR_WIDTH, bar)
        self.assertIn('100%', bar)


class TestTelegramNotifier(unittest.TestCase):
    def _make_notifier(self):
        n = sup.TelegramNotifier('bot_token', '12345')
        n.begin('v1.0.0', 'v1.1.0')
        return n

    def _mock_response(self, body: dict):
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = json.dumps(body).encode()
        resp.status = 200
        return resp

    def test_send_progress_calls_sendMessage_first(self):
        n = self._make_notifier()
        api_response = {'result': {'message_id': 99}}
        mock_resp = self._mock_response(api_response)

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            n.send_progress(1, 6, 'Fetching tags')

        mock_open.assert_called_once()
        req_arg = mock_open.call_args[0][0]
        payload = json.loads(req_arg.data)
        self.assertEqual(payload['chat_id'], '12345')
        self.assertIn('sendMessage', req_arg.full_url)
        self.assertEqual(n.message_id, 99)

    def test_send_progress_edits_existing_message(self):
        n = self._make_notifier()
        n.message_id = 99  # simulate already sent
        mock_resp = self._mock_response({'result': {}})

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            n.send_progress(2, 6, 'Verifying')

        req_arg = mock_open.call_args[0][0]
        self.assertIn('editMessageText', req_arg.full_url)
        payload = json.loads(req_arg.data)
        self.assertEqual(payload['message_id'], 99)

    def test_send_failure_always_sends_new_message(self):
        n = self._make_notifier()
        n.message_id = 99  # even with existing message_id
        mock_resp = self._mock_response({'result': {'message_id': 100}})

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            n.send_failure(4, 6, 'Health check timed out')

        req_arg = mock_open.call_args[0][0]
        self.assertIn('sendMessage', req_arg.full_url)
        payload = json.loads(req_arg.data)
        self.assertIn('FAILED', payload['text'])
        self.assertIn('Health check timed out', payload['text'])

    def test_no_api_call_when_no_token(self):
        n = sup.TelegramNotifier('', '12345')
        n.begin('v1.0.0', 'v1.1.0')
        with patch('urllib.request.urlopen') as mock_open:
            n.send_progress(1, 6, 'test')
        mock_open.assert_not_called()

    def test_send_success_edits_message(self):
        n = self._make_notifier()
        n.message_id = 99
        mock_resp = self._mock_response({'result': {}})

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            n.send_success('v1.1.0')

        req_arg = mock_open.call_args[0][0]
        self.assertIn('editMessageText', req_arg.full_url)
        payload = json.loads(req_arg.data)
        self.assertIn('v1.1.0', payload['text'])


if __name__ == '__main__':
    unittest.main()
