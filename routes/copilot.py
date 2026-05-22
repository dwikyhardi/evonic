"""GitHub Copilot integration routes.

Implements the OAuth Device Authorization Grant (RFC 8628) against
github.com (or a GitHub Enterprise Server host) to obtain a personal
access token that can call the private Copilot proxy at
`https://api.githubcopilot.com`, and exposes endpoints that sync the
discovered Copilot models into the `llm_models` table so they appear on
the `/system#models` page like any other provider.

NOTE on compliance: the Copilot endpoint is not officially published.
This integration is opt-in and only useful for users who already have
their own GitHub Copilot subscription and accept that use of a non-
official client may violate the Copilot Terms of Service. Evonic does
not host any credentials on behalf of users — the OAuth token is stored
locally in this instance's SQLite database only.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request

from models.db import db


_logger = logging.getLogger(__name__)

copilot_bp = Blueprint("copilot", __name__)

# GitHub OAuth client_id for the device flow. We use Evonic's own
# OAuth App so the consent screen shows "Authorize Evonic" rather than a
# third-party app name. The Copilot proxy (`api.githubcopilot.com`) gates
# access primarily on the user's active Copilot subscription; the
# integrator headers in `_copilot_headers` (Copilot-Integration-Id:
# vscode-chat, Editor-Version, …) are what unlock the full model catalog.
_CLIENT_ID = "Ov23licrrQqgCTqNjfvV"

# Settings keys used to persist the token + (optional) enterprise host.
_SETTING_TOKEN = "github_copilot_token"
_SETTING_ENTERPRISE_HOST = "github_copilot_enterprise_host"

# Identify as the VS Code Copilot Chat integrator so the Copilot proxy
# returns the full model catalog. Otherwise the proxy classifies us as the
# restricted `copilot-language-server` integrator, which only allows a tiny
# legacy model list and rejects modern models with HTTP 400:
#   "The requested model is not available for integrator
#    \"copilot-language-server\"..."
_USER_AGENT = "GithubCopilot/1.155.0"
_EDITOR_VERSION = "vscode/1.99.3"
_EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.7"
_INTEGRATION_ID = "vscode-chat"

# Provider tag and api_format used for rows inserted into `llm_models`.
_PROVIDER = "github_copilot"
_API_FORMAT = "openai"


# ---------- helpers ----------

def _normalize_host(value: Optional[str]) -> Optional[str]:
    """Strip scheme + trailing slash from a host/URL."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if "://" in value:
        try:
            value = urlparse(value).netloc or value
        except Exception:
            pass
    return value.replace("https://", "").replace("http://", "").rstrip("/")


def _device_urls(host: str) -> Tuple[str, str]:
    return (
        f"https://{host}/login/device/code",
        f"https://{host}/login/oauth/access_token",
    )


def _copilot_base(enterprise_host: Optional[str]) -> str:
    if enterprise_host:
        return f"https://copilot-api.{enterprise_host}"
    return "https://api.githubcopilot.com"


def _stored_token() -> Optional[str]:
    return db.get_setting(_SETTING_TOKEN)


def _stored_enterprise_host() -> Optional[str]:
    return db.get_setting(_SETTING_ENTERPRISE_HOST)


def _copilot_headers(token: str) -> Dict[str, str]:
    """Headers required to talk to api.githubcopilot.com.

    Identifies the request as coming from the VS Code Copilot Chat
    integrator so the proxy returns the full model allow-list. Without the
    `Copilot-Integration-Id` header the proxy falls back to the restricted
    `copilot-language-server` integrator (only legacy models available).
    """
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "Editor-Version": _EDITOR_VERSION,
        "Editor-Plugin-Version": _EDITOR_PLUGIN_VERSION,
        "Copilot-Integration-Id": _INTEGRATION_ID,
        "Openai-Intent": "conversation-edits",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _count_copilot_models() -> int:
    return sum(
        1
        for m in db.get_llm_models()
        if (m.get("provider") or "").lower() == _PROVIDER
    )


# ---------- device flow ----------

@copilot_bp.route("/api/copilot/auth/start", methods=["POST"])
def api_copilot_auth_start():
    """Begin the GitHub OAuth device-authorization flow.

    Body (optional): {"enterprise_host": "company.ghe.com"}
    Returns: {device_code, user_code, verification_uri, interval, expires_in}
    """
    data = request.get_json(silent=True) or {}
    enterprise_host = _normalize_host(data.get("enterprise_host"))
    host = enterprise_host or "github.com"
    device_url, _ = _device_urls(host)

    try:
        resp = requests.post(
            device_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            json={"client_id": _CLIENT_ID, "scope": "read:user"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return jsonify({"success": False, "error": f"network error: {exc}"}), 502

    if resp.status_code != 200:
        return jsonify(
            {
                "success": False,
                "error": f"device-code request failed: HTTP {resp.status_code}",
                "detail": resp.text[:300],
            }
        ), 502

    body = resp.json()
    return jsonify(
        {
            "success": True,
            "device_code": body.get("device_code"),
            "user_code": body.get("user_code"),
            "verification_uri": body.get("verification_uri"),
            "interval": body.get("interval", 5),
            "expires_in": body.get("expires_in", 900),
            "enterprise_host": enterprise_host,
        }
    )


@copilot_bp.route("/api/copilot/auth/poll", methods=["POST"])
def api_copilot_auth_poll():
    """Poll once for the OAuth access token.

    Body: {device_code, enterprise_host?}
    Returns one of:
      - {"success": true, "status": "pending"}
      - {"success": true, "status": "slow_down", "interval": N}
      - {"success": true, "status": "success", "user": "octocat"}
      - {"success": false, "status": "error", "error": "..."}
    """
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code")
    if not device_code:
        return jsonify({"success": False, "error": "device_code is required"}), 400

    enterprise_host = _normalize_host(data.get("enterprise_host"))
    host = enterprise_host or "github.com"
    _, token_url = _device_urls(host)

    try:
        resp = requests.post(
            token_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            json={
                "client_id": _CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return jsonify({"success": False, "error": f"network error: {exc}"}), 502

    if resp.status_code >= 400:
        return jsonify(
            {
                "success": False,
                "error": f"token-poll failed: HTTP {resp.status_code}",
                "detail": resp.text[:300],
            }
        ), 502

    body = resp.json()

    if body.get("access_token"):
        token = body["access_token"]
        db.set_setting(_SETTING_TOKEN, token)
        if enterprise_host:
            db.set_setting(_SETTING_ENTERPRISE_HOST, enterprise_host)
        else:
            # Clear any previously stored enterprise host on github.com login
            db.set_setting(_SETTING_ENTERPRISE_HOST, "")

        # Best-effort identity lookup so the UI can show "Connected as @user".
        user_login = None
        try:
            api_host = enterprise_host or "api.github.com"
            api_base = (
                f"https://{api_host}/api/v3"
                if enterprise_host
                else f"https://{api_host}"
            )
            ur = requests.get(
                f"{api_base}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": _USER_AGENT,
                },
                timeout=10,
            )
            if ur.status_code == 200:
                user_login = ur.json().get("login")
        except Exception:
            pass

        return jsonify(
            {
                "success": True,
                "status": "success",
                "user": user_login,
                "enterprise_host": enterprise_host,
            }
        )

    err = body.get("error")
    if err == "authorization_pending":
        return jsonify({"success": True, "status": "pending"})
    if err == "slow_down":
        return jsonify(
            {
                "success": True,
                "status": "slow_down",
                "interval": body.get("interval", 10),
            }
        )

    return jsonify(
        {
            "success": False,
            "status": "error",
            "error": err or "unknown_error",
            "detail": body.get("error_description"),
        }
    ), 400


# ---------- status / disconnect ----------

@copilot_bp.route("/api/copilot/status", methods=["GET"])
def api_copilot_status():
    """Report whether a Copilot token is stored and how many models exist."""
    token = _stored_token()
    enterprise_host = _stored_enterprise_host() or None
    return jsonify(
        {
            "connected": bool(token),
            "model_count": _count_copilot_models(),
            "enterprise_host": enterprise_host,
        }
    )


@copilot_bp.route("/api/copilot/disconnect", methods=["POST"])
def api_copilot_disconnect():
    """Remove the stored token and (optionally) delete imported Copilot models.

    Body (optional): {"remove_models": true}
    """
    data = request.get_json(silent=True) or {}
    remove_models = bool(data.get("remove_models"))

    db.set_setting(_SETTING_TOKEN, "")
    db.set_setting(_SETTING_ENTERPRISE_HOST, "")

    removed = 0
    if remove_models:
        for m in db.get_llm_models():
            if (m.get("provider") or "").lower() == _PROVIDER:
                if db.delete_model(m["id"]):
                    removed += 1

    return jsonify({"success": True, "removed_models": removed})


# ---------- model sync ----------

def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _fetch_copilot_models(token: str, enterprise_host: Optional[str]) -> List[Dict[str, Any]]:
    base = _copilot_base(enterprise_host)
    # The Copilot proxy intermittently misroutes requests to the legacy
    # `copilot-language-server` integrator bucket even when we send the
    # `Copilot-Integration-Id: vscode-chat` header. Retry a handful of
    # times — the next TCP connection usually lands on a proxy node that
    # honours the header.
    last_text = ""
    last_status = 0
    for attempt in range(5):
        resp = requests.get(
            f"{base}/models",
            headers=_copilot_headers(token),
            timeout=15,
        )
        if resp.status_code == 200:
            break
        last_text = resp.text or ""
        last_status = resp.status_code
        if resp.status_code == 400 and "copilot-language-server" in last_text:
            _logger.warning(
                "Copilot /models hit integrator flake (attempt %d/5); retrying",
                attempt + 1,
            )
            time.sleep(min(1 + attempt, 4))
            continue
        # non-flake error — fail fast
        raise RuntimeError(
            f"Copilot /models returned HTTP {resp.status_code}: {last_text[:300]}"
        )
    else:
        raise RuntimeError(
            f"Copilot /models returned HTTP {last_status} after 5 attempts: "
            f"{last_text[:300]}"
        )
    payload = resp.json()
    items = payload.get("data") or payload.get("models") or []
    if not isinstance(items, list):
        raise RuntimeError("Unexpected /models payload shape")
    out: List[Dict[str, Any]] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        # Filter out models that aren't user-pickable or are policy-disabled.
        if m.get("model_picker_enabled") is False:
            continue
        policy = (m.get("policy") or {}).get("state")
        if policy == "disabled":
            continue
        out.append(m)
    return out


def _row_for_copilot_model(
    m: Dict[str, Any],
    token: str,
    base_url: str,
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Map a Copilot /models entry to an `llm_models` row dict."""
    caps = m.get("capabilities") or {}
    limits = caps.get("limits") or {}
    supports = caps.get("supports") or {}

    model_id = m.get("id") or ""
    name = m.get("name") or model_id or "Copilot model"

    vision = bool(supports.get("vision")) or bool(
        (limits.get("vision") or {}).get("supported_media_types")
    )

    row = {
        # Preserve existing UUID if updating in place; otherwise use a stable
        # deterministic id so a re-sync updates the same row.
        "id": (existing or {}).get("id") or f"copilot_{model_id}",
        "name": (existing or {}).get("name") or f"Copilot · {name}",
        "type": "remote",
        "provider": _PROVIDER,
        "base_url": base_url,
        "api_key": token,
        "model_name": model_id,
        "max_tokens": _safe_int(
            limits.get("max_output_tokens"),
            (existing or {}).get("max_tokens", 32768) or 32768,
        ),
        "timeout": (existing or {}).get("timeout", 120) or 120,
        "thinking": (existing or {}).get("thinking", 0) or 0,
        "thinking_budget": (existing or {}).get("thinking_budget", 0) or 0,
        "temperature": (existing or {}).get("temperature"),
        "enabled": (existing or {}).get("enabled", 1)
        if existing is not None
        else 1,
        "is_default": (existing or {}).get("is_default", 0) or 0,
        "model_max_concurrent": (existing or {}).get("model_max_concurrent", 1) or 1,
        "api_format": _API_FORMAT,
        "vision_supported": 1 if vision else 0,
        "attachments_supported": 1 if vision else 0,
    }
    return row


@copilot_bp.route("/api/copilot/sync-models", methods=["POST"])
def api_copilot_sync_models():
    """Discover Copilot models and upsert them into `llm_models`.

    Existing rows are matched by `model_name` (the Copilot model id);
    rows whose model_name no longer appears in the remote response are
    left in place but flagged `enabled = 0`.
    """
    token = _stored_token()
    if not token:
        return jsonify(
            {"success": False, "error": "GitHub Copilot is not connected"}
        ), 400

    enterprise_host = _stored_enterprise_host() or None
    base_url = _copilot_base(enterprise_host)

    try:
        remote_models = _fetch_copilot_models(token, enterprise_host)
    except Exception as exc:
        _logger.warning("Copilot model sync failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 502

    existing_by_modelname: Dict[str, Dict[str, Any]] = {}
    for m in db.get_llm_models():
        if (m.get("provider") or "").lower() != _PROVIDER:
            continue
        mn = m.get("model_name")
        if mn:
            existing_by_modelname[mn] = m

    remote_ids = set()
    added = 0
    updated = 0
    for entry in remote_models:
        model_id = entry.get("id")
        if not model_id:
            continue
        remote_ids.add(model_id)
        existing = existing_by_modelname.get(model_id)
        row = _row_for_copilot_model(entry, token, base_url, existing=existing)
        if existing:
            db.update_model(existing["id"], row)
            updated += 1
        else:
            db.create_model(row)
            added += 1

    # Disable rows that no longer appear remotely so the user does not pick a
    # stale model. We don't delete them in case the user customised the row.
    disabled = 0
    for model_name, row in existing_by_modelname.items():
        if model_name not in remote_ids and row.get("enabled"):
            if db.update_model(row["id"], {"enabled": 0}):
                disabled += 1

    return jsonify(
        {
            "success": True,
            "added": added,
            "updated": updated,
            "disabled": disabled,
            "total_remote": len(remote_models),
            "synced_at": int(time.time()),
        }
    )
