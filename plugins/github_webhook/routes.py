"""
GitHub Webhook Plugin — Flask Route Handlers

Endpoint:
  POST /webhook/github_webhook  — receives GitHub webhooks
"""

import hashlib
import hmac
import json
import logging
import os
import threading

from flask import Blueprint, jsonify, request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_logger = logging.getLogger("github_webhook")
PLUGIN_ID = "github_webhook"


def _plugin_log(level: str, message: str):
    """Log a message to the plugin-scoped log (visible in plugin detail > Logs tab)."""
    try:
        from backend.plugin_manager import plugin_manager
        plugin_manager.add_log(PLUGIN_ID, level, message)
    except Exception:
        pass


def _log(level: str, message: str):
    """Log to both the Python logger and the plugin-scoped log."""
    getattr(_logger, level, _logger.info)(message)
    _plugin_log(level, message)


# Event handlers map event type -> (agent_key, prompt_key, extract_fn, allowed_actions)
EVENT_HANDLERS = {
    "release": ("RELEASE_AGENT_ID", "RELEASE_PROMPT", "_extract_release", ("published",)),
    "pull_request": ("PR_AGENT_ID", "PR_PROMPT", "_extract_pr", ("opened", "reopened", "closed", "edited")),
    "issues": ("ISSUES_AGENT_ID", "ISSUES_PROMPT", "_extract_issues", ("opened", "reopened", "closed", "edited")),
    "push": ("PUSH_AGENT_ID", "PUSH_PROMPT", "_extract_push", None),
}


def _get_config(key):
    """Get plugin config variable."""
    from backend.plugin_manager import plugin_manager
    cfg = plugin_manager.get_plugin_config("github_webhook")
    return cfg.get(key, "")


def _verify_signature(payload_body: bytes) -> bool:
    """Verify GitHub HMAC-SHA256 signature.

    Returns True only if WEBHOOK_SECRET is configured AND signature matches.
    NEVER accepts unauthenticated requests.
    """
    secret = _get_config("WEBHOOK_SECRET")
    if not secret:
        _log("error", "WEBHOOK_SECRET is not configured — rejecting webhook")
        return False

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        return False

    expected = signature_header[7:]  # strip "sha256="
    computed = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, expected)


def _render_template(template: str, data: dict) -> str:
    """Render a template string with {{variable}} placeholders."""
    result = template
    for key, value in data.items():
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value) if value else "")
    return result


# ==================== Extractors ====================

def _extract_release(data: dict) -> dict:
    """Extract template variables from a release event."""
    release = data.get("release", {})
    repo = data.get("repository", {})
    return {
        "tag_name": release.get("tag_name", ""),
        "name": release.get("name", ""),
        "body": release.get("body", ""),
        "html_url": release.get("html_url", ""),
        "repository": repo.get("full_name", ""),
        "action": data.get("action", ""),
    }


def _extract_pr(data: dict) -> dict:
    """Extract template variables from a pull_request event."""
    pr = data.get("pull_request", {})
    repo = data.get("repository", {})
    return {
        "title": pr.get("title", ""),
        "body": pr.get("body", ""),
        "html_url": pr.get("html_url", ""),
        "state": pr.get("state", ""),
        "repository": repo.get("full_name", ""),
        "action": data.get("action", ""),
    }


def _extract_issues(data: dict) -> dict:
    """Extract template variables from an issues event."""
    issue = data.get("issue", {})
    repo = data.get("repository", {})
    return {
        "title": issue.get("title", ""),
        "body": issue.get("body", ""),
        "html_url": issue.get("html_url", ""),
        "state": issue.get("state", ""),
        "repository": repo.get("full_name", ""),
        "action": data.get("action", ""),
    }


def _extract_push(data: dict) -> dict:
    """Extract template variables from a push event."""
    repo = data.get("repository", {})
    commits = data.get("commits", [])
    return {
        "ref": data.get("ref", ""),
        "commits_count": str(len(commits)),
        "repository": repo.get("full_name", ""),
        "compare": data.get("compare_url", ""),
        "action": "push",
    }


# ==================== Dispatch ====================

def _handle_event(event: str, data: dict):
    """Dispatch an event to the appropriate handler."""
    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        _log("info", "No handler for event type: %s" % event)
        return

    agent_key, prompt_key, extractor_name, allowed_actions = handler

    # Check action filter (if applicable)
    action = data.get("action", "")
    if allowed_actions is not None:
        if not action or action not in allowed_actions:
            _log("info", "Event %s action=%s — ignoring (allowed: %s)" % (event, action or "<none>", allowed_actions))
            return

    # Get config
    agent_id = _get_config(agent_key)
    if not agent_id:
        _log("info", "Event %s — %s not configured, skipping" % (event, agent_key))
        return

    prompt_template = _get_config(prompt_key)
    if not prompt_template:
        _log("warn", "Event %s — %s not configured" % (event, prompt_key))
        return

    # Extract variables
    extractor = globals().get(extractor_name)
    if extractor is None:
        _log("error", "Extractor %s not found" % extractor_name)
        return

    template_vars = extractor(data)
    rendered = _render_template(prompt_template, template_vars)

    _log("info", "Notifying agent=%s about %s event" % (agent_id, event))

    # Fire-and-forget in background thread
    def _notify():
        try:
            from backend.agent_runtime import agent_runtime
            agent_runtime.handle_message(
                agent_id=agent_id,
                external_user_id="__webhook__github",
                message=rendered,
                channel_id=None,
            )
            _log("info", "Agent %s notified for %s event" % (agent_id, event))
        except Exception as e:
            _log("error", "Failed to notify agent %s: %s" % (agent_id, e))

    threading.Thread(target=_notify, daemon=True).start()


# ==================== Blueprint ====================

def create_blueprint():
    """Create the Flask Blueprint for this plugin."""
    bp = Blueprint(
        "github_webhook_plugin",
        __name__,
        url_prefix="/webhook/github_webhook",
    )

    @bp.route("/", methods=["POST"])
    def webhook():
        """Main webhook endpoint — verifies HMAC and routes by event type."""
        # Verify signature
        payload_body = request.get_data()
        if not _verify_signature(payload_body):
            _log("warn", "Invalid signature from %s" % request.remote_addr)
            return jsonify({"error": "Invalid signature"}), 403

        # Parse event type
        event = request.headers.get("X-GitHub-Event", "")
        if not event:
            return jsonify({"error": "Missing X-GitHub-Event header"}), 400

        # Parse payload
        try:
            data = json.loads(payload_body)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON payload"}), 400

        # Route by event type
        if event == "ping":
            _log("info", "Ping received from GitHub")
            return jsonify({"msg": "pong"})

        _log("info", "Received %s event from GitHub" % event)
        _handle_event(event, data)
        return jsonify({"msg": "ok", "event": event})

    return bp
