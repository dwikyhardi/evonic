"""Routes for the system update UI and API."""

import json
import queue

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

from backend import update_manager

update_bp = Blueprint('update', __name__)


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@update_bp.route('/system/update')
def update_page():
    return render_template('update.html')


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@update_bp.route('/api/system/update/check', methods=['GET'])
def api_update_check():
    force = request.args.get('force', '').lower() in ('1', 'true')
    result = update_manager.check_for_update(force=force)
    return jsonify(result)


@update_bp.route('/api/system/update/status', methods=['GET'])
def api_update_status():
    return jsonify(update_manager.get_status())


@update_bp.route('/api/system/update/start', methods=['POST'])
def api_update_start():
    data = request.get_json(silent=True) or {}
    tag = data.get('tag')
    result = update_manager.start_update(tag=tag)
    if 'error' in result:
        return jsonify(result), 409
    return jsonify(result)


@update_bp.route('/api/system/update/rollback', methods=['POST'])
def api_update_rollback():
    result = update_manager.trigger_rollback()
    if 'error' in result:
        return jsonify(result), 409
    return jsonify(result)


@update_bp.route('/api/system/update/restart', methods=['POST'])
def api_update_restart():
    result = update_manager.trigger_restart()
    return jsonify(result)


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

@update_bp.route('/api/system/update/stream', methods=['GET'])
def api_update_stream():
    """SSE endpoint for real-time update progress. Follows the same pattern
    as the approval stream in routes/agents.py."""
    q = update_manager.register_listener()

    def generate():
        try:
            # Send initial status immediately
            status = update_manager.get_status()
            yield f"event: status\ndata: {json.dumps(status)}\n\n"

            while True:
                try:
                    snapshot = q.get(timeout=30)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue

                yield f"event: status\ndata: {json.dumps(snapshot)}\n\n"

                # If terminal state, send done event and close
                if snapshot.get('status') in ('success', 'failed'):
                    yield f"event: done\ndata: {json.dumps({'status': snapshot['status']})}\n\n"
        finally:
            update_manager.unregister_listener(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )
