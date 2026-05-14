import threading

from flask import Blueprint, render_template, jsonify, request

from models.db import db

sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('/sessions')
def sessions():
    """Chat sessions dashboard"""
    return render_template('sessions.html')


@sessions_bp.route('/api/sessions')
def api_list_sessions():
    search = request.args.get('search', '').strip() or None
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    exclude_test = request.args.get('exclude_test', '1') != '0'
    sessions, total = db.get_all_sessions(search=search, limit=limit, offset=offset,
                                          exclude_test=exclude_test)
    return jsonify({'sessions': sessions, 'total': total})


@sessions_bp.route('/api/sessions/<session_id>')
def api_get_session(session_id):
    session = db.get_session_with_details(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    messages = db.get_session_messages_full(session_id)
    return jsonify({'session': session, 'messages': messages})


@sessions_bp.route('/api/sessions/<session_id>/poll')
def api_session_poll(session_id):
    """Poll for new messages since after_id."""
    after_id = request.args.get('after', 0, type=int)
    messages = db.get_new_messages(session_id, after_id)
    return jsonify({'messages': messages})


@sessions_bp.route('/api/sessions/<session_id>/reply', methods=['POST'])
def api_session_reply(session_id):
    data = request.get_json()
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Text is required'}), 400
    perspective = (data.get('perspective') or 'B').strip()
    from backend.agent_runtime import agent_runtime
    if perspective == 'A':
        ok = agent_runtime.send_as_user(session_id, text)
    else:
        ok = agent_runtime.send_as_bot(session_id, text)
    if not ok:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({'success': True})


@sessions_bp.route('/api/sessions/<session_id>/stop', methods=['POST'])
def api_session_stop(session_id):
    """Send a stop signal to interrupt the agent's current processing loop."""
    from backend.agent_runtime import agent_runtime
    agent_runtime.request_stop(session_id)
    return jsonify({'success': True})


@sessions_bp.route('/api/sessions/<session_id>/bot', methods=['PUT'])
def api_session_toggle_bot(session_id):
    data = request.get_json()
    enabled = data.get('enabled', True)
    db.set_session_bot_enabled(session_id, enabled)
    return jsonify({'success': True, 'bot_enabled': enabled})


@sessions_bp.route('/api/sessions/<session_id>/summary')
def api_session_summary(session_id):
    """Get the conversation summary for a session."""
    summary = db.get_summary(session_id)
    if summary:
        return jsonify({'summary': summary['summary'],
                        'last_message_id': summary['last_message_id'],
                        'message_count': summary['message_count'],
                        'updated_at': summary.get('updated_at')})
    return jsonify({'summary': None})


@sessions_bp.route('/api/sessions/<session_id>/summarize', methods=['POST'])
def api_force_summarize(session_id):
    """Force a fresh summarization for the session."""
    session = db.get_session_with_details(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    agent = db.get_agent(session['agent_id'])
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    from backend.agent_runtime import agent_runtime
    threading.Thread(
        target=agent_runtime._maybe_summarize,
        args=(agent, session_id),
        daemon=True
    ).start()
    return jsonify({'success': True})


@sessions_bp.route('/api/sessions/<session_id>', methods=['DELETE'])
def api_delete_session(session_id):
    db.delete_session(session_id)
    return jsonify({'success': True})


@sessions_bp.route('/api/sessions/clear-all', methods=['POST'])
def api_clear_all_sessions():
    """Delete all chat sessions, messages, summaries, and attachments
    across all agents."""
    db.clear_all_sessions()
    return jsonify({'success': True})


@sessions_bp.route('/api/attachments/clear-all', methods=['POST'])
def api_clear_all_attachments():
    """Delete every stored attachment (DB rows + on-disk files) across all
    agents and sessions, without touching chat sessions/messages."""
    deleted, freed = db.delete_all_attachments()
    return jsonify({'success': True, 'deleted': deleted, 'freed_bytes': freed})
