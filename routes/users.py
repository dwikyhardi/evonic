"""Users dashboard routes: pages + REST API for users and channel identities."""

import sqlite3

from flask import Blueprint, render_template, jsonify, request

from models.db import db

users_bp = Blueprint('users', __name__)


# ==================== Page routes ====================

@users_bp.route('/users')
def users_page():
    return render_template('users.html')


@users_bp.route('/users/<user_id>')
def user_detail_page(user_id):
    user = db.get_user(user_id)
    if not user:
        return render_template('users.html', missing_user=user_id), 404
    return render_template('user_detail.html', user_id=user_id)


# ==================== JSON API: Users ====================

@users_bp.route('/api/users', methods=['GET'])
def api_list_users():
    search = (request.args.get('search') or '').strip() or None
    return jsonify({'users': db.list_users(search=search)})


@users_bp.route('/api/users', methods=['POST'])
def api_create_user():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    note = data.get('note')
    enabled = bool(data.get('enabled', True))
    try:
        user_id = db.create_user(name=name, note=note, enabled=enabled)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'id': user_id, 'user': db.get_user(user_id)}), 201


@users_bp.route('/api/users/<user_id>', methods=['GET'])
def api_get_user(user_id):
    user = db.get_user(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': user, 'identities': db.list_user_identities(user_id=user_id)})


@users_bp.route('/api/users/<user_id>', methods=['PUT'])
def api_update_user(user_id):
    if not db.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'name' in data and not (data.get('name') or '').strip():
        return jsonify({'error': 'name cannot be empty'}), 400
    db.update_user(user_id, **data)
    return jsonify({'user': db.get_user(user_id)})


@users_bp.route('/api/users/<user_id>', methods=['DELETE'])
def api_delete_user(user_id):
    if not db.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404
    db.delete_user(user_id)
    return jsonify({'success': True})


# ==================== JSON API: Channel identities ====================

@users_bp.route('/api/users/<user_id>/identities', methods=['GET'])
def api_list_identities(user_id):
    if not db.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'identities': db.list_user_identities(user_id=user_id)})


@users_bp.route('/api/users/<user_id>/identities', methods=['POST'])
def api_create_identity(user_id):
    if not db.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404
    data = request.get_json(silent=True) or {}
    channel_id = (data.get('channel_id') or '').strip()
    external_user_id = data.get('external_user_id')
    if external_user_id is not None:
        external_user_id = str(external_user_id).strip()
    if not channel_id or not external_user_id:
        return jsonify({'error': 'channel_id and external_user_id are required'}), 400
    if not db.get_channel(channel_id):
        return jsonify({'error': 'channel_id does not exist'}), 400
    agent_id = data.get('agent_id') or None
    if agent_id and not db.get_agent(agent_id):
        return jsonify({'error': 'agent_id does not exist'}), 400
    enabled = bool(data.get('enabled', True))
    try:
        identity_id = db.create_identity(
            user_id, channel_id, external_user_id,
            agent_id=agent_id, enabled=enabled,
        )
    except sqlite3.IntegrityError:
        return jsonify({
            'error': 'Identity already exists for this channel + external_user_id',
        }), 409
    return jsonify({'id': identity_id, 'identity': db.get_identity(identity_id)}), 201


@users_bp.route('/api/identities/<identity_id>', methods=['PUT'])
def api_update_identity(identity_id):
    if not db.get_identity(identity_id):
        return jsonify({'error': 'Identity not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'agent_id' in data and data['agent_id']:
        if not db.get_agent(data['agent_id']):
            return jsonify({'error': 'agent_id does not exist'}), 400
    try:
        db.update_identity(identity_id, **data)
    except sqlite3.IntegrityError:
        return jsonify({
            'error': 'Identity conflict: (channel_id, external_user_id) must be unique',
        }), 409
    return jsonify({'identity': db.get_identity(identity_id)})


@users_bp.route('/api/identities/<identity_id>', methods=['DELETE'])
def api_delete_identity(identity_id):
    if not db.get_identity(identity_id):
        return jsonify({'error': 'Identity not found'}), 404
    db.delete_identity(identity_id)
    return jsonify({'success': True})


# ==================== Helpers used by the dashboard JS ====================

@users_bp.route('/api/channels', methods=['GET'])
def api_list_all_channels():
    """Flat list of all channels across agents — used by user detail page picker."""
    agents = db.get_agents()
    channels = []
    for ag in agents:
        for ch in db.get_channels(ag['id']):
            channels.append({
                'id': ch['id'],
                'name': ch.get('name'),
                'type': ch.get('type'),
                'agent_id': ag['id'],
                'agent_name': ag.get('name'),
                'enabled': bool(ch.get('enabled')),
            })
    return jsonify({'channels': channels})


@users_bp.route('/api/agents/<agent_id>/routed-identities', methods=['GET'])
def api_agent_routed_identities(agent_id):
    """Identities currently routed to a specific agent (for agent detail page)."""
    if not db.get_agent(agent_id):
        return jsonify({'error': 'Agent not found'}), 404
    return jsonify({'identities': db.list_user_identities(agent_id=agent_id)})
