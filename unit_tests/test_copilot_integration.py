"""
Unit tests for the GitHub Copilot integration.

Covers:
- Pure helpers in `routes.copilot` (`_normalize_host`, `_copilot_base`,
  `_copilot_headers`, `_row_for_copilot_model`).
- Helpers in `backend.llm_client` (`_is_github_copilot_url`,
  `_apply_copilot_headers`).
- The `_fetch_copilot_models` retry behavior on the proxy's intermittent
  `copilot-language-server` 400 error.
- `LLMClient.chat_completion` transparent retry on the same 400.
- Flask endpoints (`status`, `disconnect`, `sync-models`, `auth/start`).

Network calls are stubbed via monkeypatched `requests.get`/`requests.post`
and `time.sleep` is patched out so the retry loops run instantly.
"""

import os
import sys

import pytest

# Make the project root importable for `routes.copilot` and `backend.llm_client`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes import copilot as copilot_mod  # noqa: E402
from routes.copilot import (  # noqa: E402
    _copilot_base,
    _copilot_headers,
    _fetch_copilot_models,
    _normalize_host,
    _row_for_copilot_model,
    _PROVIDER,
    _SETTING_TOKEN,
    _SETTING_ENTERPRISE_HOST,
)
from backend.llm_client import (  # noqa: E402
    LLMClient,
    _apply_copilot_headers,
    _is_github_copilot_url,
)


# ---------------------------------------------------------------------------
# Stub Response object — mimics just enough of `requests.Response` for our tests.
# ---------------------------------------------------------------------------

class _StubResponse:
    """Minimal stand-in for `requests.Response` returned by stubbed callers."""

    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        # Mirror `requests`: when text isn't given, derive from json.
        self.text = text if text is not None else (
            "" if json_data is None else str(json_data)
        )

    def json(self):
        return self._json


def _auth(client):
    """Authenticate the test client session (mirrors test_history_api.py)."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    return client


# ===========================================================================
# Pure helpers — routes/copilot.py
# ===========================================================================

class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("github.com", "github.com"),
            ("https://github.com/", "github.com"),
            ("http://ghe.acme.com", "ghe.acme.com"),
            ("https://ghe.acme.com/some/path", "ghe.acme.com"),
            ("ghe.acme.com/", "ghe.acme.com"),
        ],
    )
    def test_normalize_host(self, value, expected):
        assert _normalize_host(value) == expected


class TestCopilotBase:
    def test_default_base_is_public_proxy(self):
        assert _copilot_base(None) == "https://api.githubcopilot.com"

    def test_enterprise_host_uses_copilot_api_subdomain(self):
        assert _copilot_base("ghe.acme.com") == "https://copilot-api.ghe.acme.com"


class TestCopilotHeaders:
    """The integrator fingerprint is what unlocks the full Copilot model
    catalog at `api.githubcopilot.com`. If any of these headers regress, the
    proxy bucket-routes us back to `copilot-language-server` and modern
    models stop working — so they're explicitly verified here.
    """

    def test_returns_full_integrator_fingerprint(self):
        h = _copilot_headers("gho_test_token")
        assert h["Authorization"] == "Bearer gho_test_token"
        # The three headers that route to the `vscode-chat` integrator.
        assert h["User-Agent"].startswith("GithubCopilot/")
        assert h["Editor-Version"].startswith("vscode/")
        assert h["Editor-Plugin-Version"].startswith("copilot-chat/")
        assert h["Copilot-Integration-Id"] == "vscode-chat"
        # Telemetry header sent by the official client.
        assert h["Openai-Intent"] == "conversation-edits"
        # JSON content-type for POST bodies.
        assert h["Content-Type"] == "application/json"


# ===========================================================================
# backend/llm_client helpers
# ===========================================================================

class TestIsGithubCopilotUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (None, False),
            ("", False),
            ("https://api.openai.com/v1", False),
            ("https://api.anthropic.com", False),
            ("https://api.githubcopilot.com", True),
            ("https://api.githubcopilot.com/v1", True),
            # Enterprise host pattern: copilot-api.<ghes-host>
            ("https://copilot-api.ghe.acme.com", True),
        ],
    )
    def test_url_detection(self, url, expected):
        assert _is_github_copilot_url(url) is expected


class TestApplyCopilotHeaders:
    def test_no_op_for_non_copilot_url(self):
        h = {"Existing": "1"}
        _apply_copilot_headers(h, "https://api.openai.com", is_agent=True)
        assert h == {"Existing": "1"}

    def test_injects_full_fingerprint_for_copilot_url(self):
        h = {}
        _apply_copilot_headers(h, "https://api.githubcopilot.com", is_agent=True)
        assert h["User-Agent"].startswith("GithubCopilot/")
        assert h["Editor-Version"].startswith("vscode/")
        assert h["Editor-Plugin-Version"].startswith("copilot-chat/")
        assert h["Copilot-Integration-Id"] == "vscode-chat"
        assert h["Openai-Intent"] == "conversation-edits"
        assert h["x-initiator"] == "agent"

    def test_initiator_user_when_not_agent(self):
        h = {}
        _apply_copilot_headers(h, "https://api.githubcopilot.com", is_agent=False)
        assert h["x-initiator"] == "user"

    def test_vision_request_header(self):
        h = {}
        _apply_copilot_headers(
            h, "https://api.githubcopilot.com", is_agent=True, is_vision=True
        )
        assert h["Copilot-Vision-Request"] == "true"

    def test_vision_header_absent_by_default(self):
        h = {}
        _apply_copilot_headers(h, "https://api.githubcopilot.com", is_agent=True)
        assert "Copilot-Vision-Request" not in h

    def test_idempotent_does_not_override_caller_headers(self):
        # Caller-provided headers must win (setdefault semantics).
        h = {"User-Agent": "my-custom-ua/9.9"}
        _apply_copilot_headers(h, "https://api.githubcopilot.com", is_agent=True)
        assert h["User-Agent"] == "my-custom-ua/9.9"


# ===========================================================================
# _row_for_copilot_model — mapping the /models entry to an llm_models row
# ===========================================================================

class TestRowForCopilotModel:
    def _sample_entry(self, **overrides):
        m = {
            "id": "claude-sonnet-4.6",
            "name": "Claude Sonnet 4.6",
            "model_picker_enabled": True,
            "policy": {"state": "enabled"},
            "capabilities": {
                "limits": {"max_output_tokens": 8192},
                "supports": {"vision": True},
            },
        }
        m.update(overrides)
        return m

    def test_basic_row_shape(self):
        row = _row_for_copilot_model(
            self._sample_entry(),
            token="gho_x",
            base_url="https://api.githubcopilot.com",
        )
        assert row["id"] == "copilot_claude-sonnet-4.6"
        assert row["model_name"] == "claude-sonnet-4.6"
        assert row["name"] == "Copilot · Claude Sonnet 4.6"
        assert row["provider"] == _PROVIDER
        assert row["api_format"] == "openai"
        assert row["base_url"] == "https://api.githubcopilot.com"
        assert row["api_key"] == "gho_x"
        assert row["max_tokens"] == 8192
        assert row["enabled"] == 1
        assert row["vision_supported"] == 1
        assert row["attachments_supported"] == 1

    def test_falls_back_to_default_max_tokens_when_missing(self):
        e = self._sample_entry()
        e["capabilities"]["limits"].pop("max_output_tokens")
        row = _row_for_copilot_model(
            e, token="t", base_url="https://api.githubcopilot.com"
        )
        # Default per implementation when no existing row is given.
        assert row["max_tokens"] == 32768

    def test_preserves_existing_id_and_user_customisations(self):
        existing = {
            "id": "uuid-existing-row",
            "name": "User-renamed model",
            "timeout": 250,
            "is_default": 1,
            "model_max_concurrent": 4,
            "temperature": 0.3,
            "enabled": 0,
        }
        row = _row_for_copilot_model(
            self._sample_entry(),
            token="t",
            base_url="https://api.githubcopilot.com",
            existing=existing,
        )
        assert row["id"] == "uuid-existing-row"
        assert row["name"] == "User-renamed model"
        assert row["timeout"] == 250
        assert row["is_default"] == 1
        assert row["model_max_concurrent"] == 4
        assert row["temperature"] == 0.3
        # `enabled` from existing row is preserved (even when 0).
        assert row["enabled"] == 0

    def test_vision_flag_from_limits_media_types(self):
        # `supports.vision` is absent — vision should be detected from
        # the `limits.vision.supported_media_types` array.
        e = {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "capabilities": {
                "limits": {"vision": {"supported_media_types": ["image/png"]}},
                "supports": {},
            },
        }
        row = _row_for_copilot_model(
            e, token="t", base_url="https://api.githubcopilot.com"
        )
        assert row["vision_supported"] == 1
        assert row["attachments_supported"] == 1

    def test_no_vision_when_unsupported(self):
        e = {
            "id": "gpt-3.5-turbo",
            "name": "GPT-3.5 Turbo",
            "capabilities": {"limits": {}, "supports": {}},
        }
        row = _row_for_copilot_model(
            e, token="t", base_url="https://api.githubcopilot.com"
        )
        assert row["vision_supported"] == 0
        assert row["attachments_supported"] == 0


# ===========================================================================
# _fetch_copilot_models — retry on integrator flake
# ===========================================================================

class TestFetchCopilotModelsRetry:
    def test_succeeds_on_first_try(self, monkeypatch):
        payload = {
            "data": [
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "model_picker_enabled": True,
                    "policy": {"state": "enabled"},
                }
            ]
        }
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            assert url == "https://api.githubcopilot.com/models"
            # Integrator header must be on the wire.
            assert headers.get("Copilot-Integration-Id") == "vscode-chat"
            return _StubResponse(200, json_data=payload)

        monkeypatch.setattr(copilot_mod.requests, "get", fake_get)
        # Don't actually sleep in retry tests.
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        out = _fetch_copilot_models("gho_token", None)
        assert calls["n"] == 1
        assert len(out) == 1
        assert out[0]["id"] == "gpt-4o"

    def test_retries_on_integrator_flake_then_succeeds(self, monkeypatch):
        flake_text = (
            '{"error":{"message":"The requested model is not available for '
            'integrator \\"copilot-language-server\\". Available models: '
            "[gpt-4.1 claude-opus-4.7 gpt-5.5]\"}}"
        )
        payload = {"data": [{"id": "claude-sonnet-4.6", "name": "Claude Sonnet 4.6"}]}

        responses = [
            _StubResponse(400, text=flake_text),
            _StubResponse(400, text=flake_text),
            _StubResponse(200, json_data=payload),
        ]
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            return responses.pop(0)

        sleep_calls = []
        monkeypatch.setattr(copilot_mod.requests, "get", fake_get)
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda s: sleep_calls.append(s))

        out = _fetch_copilot_models("gho_token", None)

        assert calls["n"] == 3, "must retry past the two flake responses"
        # Two sleeps (one per failed attempt before the success).
        assert len(sleep_calls) == 2
        assert all(s > 0 for s in sleep_calls)
        assert len(out) == 1
        assert out[0]["id"] == "claude-sonnet-4.6"

    def test_fails_fast_on_non_flake_error(self, monkeypatch):
        # 401 (auth problem) must NOT be retried.
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            return _StubResponse(401, text='{"message":"Bad credentials"}')

        monkeypatch.setattr(copilot_mod.requests, "get", fake_get)
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        with pytest.raises(RuntimeError) as ei:
            _fetch_copilot_models("gho_token", None)
        assert "401" in str(ei.value)
        assert calls["n"] == 1, "non-flake errors must not trigger retries"

    def test_gives_up_after_5_attempts(self, monkeypatch):
        flake_text = "integrator copilot-language-server"
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            return _StubResponse(400, text=flake_text)

        monkeypatch.setattr(copilot_mod.requests, "get", fake_get)
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        with pytest.raises(RuntimeError) as ei:
            _fetch_copilot_models("gho_token", None)
        assert calls["n"] == 5
        assert "after 5 attempts" in str(ei.value)

    def test_filters_out_disabled_and_non_picker_models(self, monkeypatch):
        payload = {
            "data": [
                {
                    "id": "ok-model",
                    "name": "OK",
                    "model_picker_enabled": True,
                    "policy": {"state": "enabled"},
                },
                {
                    "id": "hidden-model",
                    "name": "Hidden",
                    "model_picker_enabled": False,
                },
                {
                    "id": "disabled-model",
                    "name": "Disabled",
                    "model_picker_enabled": True,
                    "policy": {"state": "disabled"},
                },
                # Malformed entry should be silently skipped.
                "not-a-dict",
            ]
        }

        monkeypatch.setattr(
            copilot_mod.requests,
            "get",
            lambda *a, **k: _StubResponse(200, json_data=payload),
        )
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        out = _fetch_copilot_models("gho_token", None)
        assert [m["id"] for m in out] == ["ok-model"]


# ===========================================================================
# LLMClient.chat_completion — integrator-flake retry
# ===========================================================================

def _make_copilot_client():
    return LLMClient(
        model_config={
            "base_url": "https://api.githubcopilot.com",
            "api_key": "gho_test",
            "model_name": "claude-sonnet-4.6",
            "timeout": 30,
            "max_tokens": 1024,
            "api_format": "openai",
        }
    )


class TestChatCompletionCopilotRetry:
    def test_request_carries_full_integrator_fingerprint(self, monkeypatch):
        seen_headers = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            seen_headers.update(headers or {})
            return _StubResponse(
                200,
                json_data={
                    "choices": [
                        {"message": {"role": "assistant", "content": "hello"},
                         "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                              "total_tokens": 2},
                },
            )

        import backend.llm_client as llm_mod
        monkeypatch.setattr(llm_mod.requests, "post", fake_post)
        monkeypatch.setattr(llm_mod.time, "sleep", lambda *_a, **_k: None)

        c = _make_copilot_client()
        result = c.chat_completion([{"role": "user", "content": "hi"}])

        assert result["success"] is True
        assert seen_headers["Authorization"] == "Bearer gho_test"
        assert seen_headers["Copilot-Integration-Id"] == "vscode-chat"
        assert seen_headers["Editor-Version"].startswith("vscode/")
        assert seen_headers["x-initiator"] == "agent"

    def test_retries_then_succeeds_on_integrator_flake(self, monkeypatch):
        flake_text = (
            '{"error":{"message":"The requested model is not available for '
            'integrator \\"copilot-language-server\\"..."}}'
        )
        success_json = {
            "choices": [
                {"message": {"role": "assistant", "content": "retried OK"},
                 "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
        responses = [
            _StubResponse(400, text=flake_text),
            _StubResponse(200, json_data=success_json),
        ]
        calls = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            return responses.pop(0)

        import backend.llm_client as llm_mod
        monkeypatch.setattr(llm_mod.requests, "post", fake_post)
        monkeypatch.setattr(llm_mod.time, "sleep", lambda *_a, **_k: None)

        c = _make_copilot_client()
        result = c.chat_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 2
        assert result["success"] is True
        assert "retried OK" in result["response"]["choices"][0]["message"]["content"]

    def test_non_copilot_400_does_not_trigger_retry(self, monkeypatch):
        # Regression guard: only the very specific Copilot integrator 400
        # should be retried. Other 400s must fail-fast.
        calls = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            return _StubResponse(400, text='{"message":"unknown model"}')

        import backend.llm_client as llm_mod
        monkeypatch.setattr(llm_mod.requests, "post", fake_post)
        monkeypatch.setattr(llm_mod.time, "sleep", lambda *_a, **_k: None)

        c = _make_copilot_client()
        result = c.chat_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1
        assert result["success"] is False
        assert result["error_type"] == "api_error"


# ===========================================================================
# Flask endpoints (auth/start, status, disconnect, sync-models)
# ===========================================================================

class TestCopilotStatusEndpoint:
    def test_status_disconnected_by_default(self):
        from app import app
        with app.test_client() as client:
            _auth(client)
            resp = client.get("/api/copilot/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["connected"] is False
            assert data["model_count"] == 0
            assert data["enterprise_host"] is None

    def test_status_connected_after_token_stored(self):
        from app import app
        from models.db import db
        db.set_setting(_SETTING_TOKEN, "gho_xyz")
        try:
            with app.test_client() as client:
                _auth(client)
                resp = client.get("/api/copilot/status")
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["connected"] is True
                assert data["model_count"] == 0
        finally:
            db.set_setting(_SETTING_TOKEN, "")


class TestCopilotDisconnectEndpoint:
    def test_disconnect_clears_token(self):
        from app import app
        from models.db import db
        db.set_setting(_SETTING_TOKEN, "gho_xyz")
        db.set_setting(_SETTING_ENTERPRISE_HOST, "ghe.acme.com")

        with app.test_client() as client:
            _auth(client)
            resp = client.post(
                "/api/copilot/disconnect",
                json={"remove_models": False},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["removed_models"] == 0

        assert (db.get_setting(_SETTING_TOKEN) or "") == ""
        assert (db.get_setting(_SETTING_ENTERPRISE_HOST) or "") == ""

    def test_disconnect_removes_models_when_requested(self):
        from app import app
        from models.db import db

        # Seed two copilot rows + one unrelated row.
        copilot_id_1 = db.create_model({
            "id": "copilot_a", "name": "Copilot · A", "type": "remote",
            "provider": _PROVIDER, "base_url": "https://api.githubcopilot.com",
            "api_key": "gho_x", "model_name": "a", "api_format": "openai",
        })
        copilot_id_2 = db.create_model({
            "id": "copilot_b", "name": "Copilot · B", "type": "remote",
            "provider": _PROVIDER, "base_url": "https://api.githubcopilot.com",
            "api_key": "gho_x", "model_name": "b", "api_format": "openai",
        })
        other_id = db.create_model({
            "id": "other_x", "name": "Other", "type": "remote",
            "provider": "openai", "base_url": "https://api.openai.com",
            "api_key": "sk-1", "model_name": "gpt-4o", "api_format": "openai",
        })

        db.set_setting(_SETTING_TOKEN, "gho_xyz")

        with app.test_client() as client:
            _auth(client)
            resp = client.post(
                "/api/copilot/disconnect",
                json={"remove_models": True},
            )
            assert resp.status_code == 200
            assert resp.get_json()["removed_models"] == 2

        remaining_ids = {m["id"] for m in db.get_llm_models()}
        assert copilot_id_1 not in remaining_ids
        assert copilot_id_2 not in remaining_ids
        # Unrelated provider must be preserved.
        assert other_id in remaining_ids


class TestCopilotAuthStartEndpoint:
    def test_proxies_device_code_response(self, monkeypatch):
        from app import app

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            return _StubResponse(
                200,
                json_data={
                    "device_code": "dev-123",
                    "user_code": "AB-CD-EF",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                    "expires_in": 900,
                },
            )

        monkeypatch.setattr(copilot_mod.requests, "post", fake_post)

        with app.test_client() as client:
            _auth(client)
            resp = client.post("/api/copilot/auth/start", json={})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["device_code"] == "dev-123"
            assert data["user_code"] == "AB-CD-EF"
            assert data["interval"] == 5

        assert captured["url"] == "https://github.com/login/device/code"
        assert captured["body"]["scope"] == "read:user"
        assert captured["body"]["client_id"]  # not empty

    def test_uses_enterprise_host_when_provided(self, monkeypatch):
        from app import app

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            return _StubResponse(
                200,
                json_data={
                    "device_code": "x", "user_code": "y",
                    "verification_uri": "https://ghe.acme.com/login/device",
                    "interval": 5, "expires_in": 900,
                },
            )

        monkeypatch.setattr(copilot_mod.requests, "post", fake_post)

        with app.test_client() as client:
            _auth(client)
            resp = client.post(
                "/api/copilot/auth/start",
                json={"enterprise_host": "https://ghe.acme.com/"},
            )
            assert resp.status_code == 200
            assert resp.get_json()["enterprise_host"] == "ghe.acme.com"

        assert captured["url"] == "https://ghe.acme.com/login/device/code"

    def test_returns_502_on_network_failure(self, monkeypatch):
        from app import app
        import requests as real_requests

        def fake_post(*a, **k):
            raise real_requests.RequestException("connection refused")

        monkeypatch.setattr(copilot_mod.requests, "post", fake_post)

        with app.test_client() as client:
            _auth(client)
            resp = client.post("/api/copilot/auth/start", json={})
            assert resp.status_code == 502
            assert resp.get_json()["success"] is False


class TestCopilotSyncModelsEndpoint:
    def test_400_when_no_token_stored(self):
        from app import app
        from models.db import db
        # Ensure clean slate.
        db.set_setting(_SETTING_TOKEN, "")

        with app.test_client() as client:
            _auth(client)
            resp = client.post("/api/copilot/sync-models")
            assert resp.status_code == 400
            assert resp.get_json()["success"] is False

    def test_sync_adds_models_and_disables_missing_ones(self, monkeypatch):
        from app import app
        from models.db import db

        db.set_setting(_SETTING_TOKEN, "gho_test")

        # Pre-seed a previously-synced copilot model that won't come back from
        # the remote — it should be disabled, not deleted.
        stale_id = db.create_model({
            "id": "copilot_stale-model",
            "name": "Copilot · Stale",
            "type": "remote",
            "provider": _PROVIDER,
            "base_url": "https://api.githubcopilot.com",
            "api_key": "gho_test",
            "model_name": "stale-model",
            "api_format": "openai",
            "enabled": 1,
        })

        remote_payload = {
            "data": [
                {
                    "id": "claude-sonnet-4.6",
                    "name": "Claude Sonnet 4.6",
                    "model_picker_enabled": True,
                    "policy": {"state": "enabled"},
                    "capabilities": {
                        "limits": {"max_output_tokens": 8192},
                        "supports": {"vision": True},
                    },
                },
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "model_picker_enabled": True,
                    "policy": {"state": "enabled"},
                    "capabilities": {"limits": {}, "supports": {}},
                },
            ]
        }

        monkeypatch.setattr(
            copilot_mod.requests,
            "get",
            lambda *a, **k: _StubResponse(200, json_data=remote_payload),
        )
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        with app.test_client() as client:
            _auth(client)
            resp = client.post("/api/copilot/sync-models")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["added"] == 2
            assert data["updated"] == 0
            assert data["disabled"] == 1
            assert data["total_remote"] == 2

        # New rows are present and enabled.
        all_models = {m["id"]: m for m in db.get_llm_models()}
        assert "copilot_claude-sonnet-4.6" in all_models
        assert all_models["copilot_claude-sonnet-4.6"]["enabled"] == 1
        assert all_models["copilot_gpt-4o"]["enabled"] == 1
        # Stale row was disabled in place (not deleted).
        assert stale_id in all_models
        assert all_models[stale_id]["enabled"] == 0

    def test_returns_502_when_remote_fails(self, monkeypatch):
        from app import app
        from models.db import db

        db.set_setting(_SETTING_TOKEN, "gho_test")

        monkeypatch.setattr(
            copilot_mod.requests,
            "get",
            lambda *a, **k: _StubResponse(401, text='{"message":"Bad credentials"}'),
        )
        monkeypatch.setattr(copilot_mod.time, "sleep", lambda *_a, **_k: None)

        with app.test_client() as client:
            _auth(client)
            resp = client.post("/api/copilot/sync-models")
            assert resp.status_code == 502
            assert resp.get_json()["success"] is False
