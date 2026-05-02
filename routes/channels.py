"""Top-level Channels dashboard routes: page + REST API.

Channels are managed independently of any single agent. Each channel still
keeps a default `agent_id` (used as fallback when no per-user identity
override exists), but creation/listing/editing happens here, not nested
under `/api/agents/<agent_id>/channels/...`.
"""

import logging

from flask import Blueprint, render_template, jsonify, request

from models.db import db

channels_bp = Blueprint('channels', __name__)

_logger = logging.getLogger(__name__)


# ==================== Page route ====================

@channels_bp.route('/channels')
def channels_page():
    return render_template('channels.html')


# ==================== Helpers ====================

def _enriched_channel(ch: dict) -> dict:
    """Decorate a raw channel row with `running` and `agent_name`."""
    from backend.channels.registry import channel_manager
    ch = dict(ch)
    ch['running'] = channel_manager.is_running(ch['id'])
    if 'agent_name' not in ch and ch.get('agent_id'):
        agent = db.get_agent(ch['agent_id'])
        ch['agent_name'] = agent.get('name') if agent else None
    return ch


def _validate_channel_payload(data: dict, *, partial: bool = False):
    """Return (error_message, status) or (None, None) when valid."""
    from backend.channels.registry import CHANNEL_TYPES

    if not partial or 'agent_id' in data:
        agent_id = (data.get('agent_id') or '').strip() if data.get('agent_id') is not None else ''
        if not agent_id:
            return 'agent_id is required', 400
        if not db.get_agent(agent_id):
            return 'agent_id does not exist', 400

    if not partial or 'type' in data:
        chan_type = (data.get('type') or '').strip() if data.get('type') is not None else ''
        if not chan_type:
            return 'type is required', 400
        if chan_type not in CHANNEL_TYPES:
            return f"Unsupported channel type '{chan_type}'", 400

    return None, None


# ==================== JSON API: list / create ====================

@channels_bp.route('/api/channels', methods=['GET'])
def api_list_channels():
    """Flat list of all channels across agents.

    Replaces the per-agent helper that used to live in `routes/users.py` —
    same URL so the user-detail page picker keeps working unchanged.
    """
    from backend.channels.registry import channel_manager
    rows = db.list_all_channels()
    channels = []
    for ch in rows:
        channels.append({
            'id': ch['id'],
            'name': ch.get('name'),
            'type': ch.get('type'),
            'agent_id': ch.get('agent_id'),
            'agent_name': ch.get('agent_name'),
            'enabled': bool(ch.get('enabled')),
            'running': channel_manager.is_running(ch['id']),
            'config': ch.get('config') or {},
        })
    return jsonify({'channels': channels})


@channels_bp.route('/api/channels', methods=['POST'])
def api_create_channel():
    data = request.get_json(silent=True) or {}
    err, status = _validate_channel_payload(data, partial=False)
    if err:
        return jsonify({'error': err}), status

    payload = {
        'agent_id': data['agent_id'],
        'type': data['type'],
        'name': (data.get('name') or '').strip(),
        'config': data.get('config') or {},
        'enabled': bool(data.get('enabled', True)),
    }
    chan_id = db.create_channel(payload)

    # Auto-start the channel after creation (mirrors the per-agent endpoint).
    if payload['enabled']:
        from backend.channels.registry import channel_manager
        try:
            channel_manager.start_channel(chan_id)
        except Exception as e:
            _logger.error("Auto-start failed for new channel %s: %s", chan_id, e)

    return jsonify({'success': True, 'channel': _enriched_channel(db.get_channel(chan_id))}), 201


# ==================== JSON API: detail / update / delete ====================

@channels_bp.route('/api/channels/<channel_id>', methods=['GET'])
def api_get_channel(channel_id):
    ch = db.get_channel(channel_id)
    if not ch:
        return jsonify({'error': 'Channel not found'}), 404
    enriched = _enriched_channel(ch)
    identities = db.list_user_identities(channel_id=channel_id)
    return jsonify({'channel': enriched, 'identities': identities})


@channels_bp.route('/api/channels/<channel_id>', methods=['PUT'])
def api_update_channel(channel_id):
    existing = db.get_channel(channel_id)
    if not existing:
        return jsonify({'error': 'Channel not found'}), 404

    data = request.get_json(silent=True) or {}
    err, status = _validate_channel_payload(data, partial=True)
    if err:
        return jsonify({'error': err}), status

    # Detect whether routing-affecting fields are changing — if so, restart.
    new_agent_id = data.get('agent_id')
    new_config = data.get('config')
    needs_restart = False
    if new_agent_id is not None and new_agent_id != existing.get('agent_id'):
        needs_restart = True
    if new_config is not None and new_config != existing.get('config'):
        needs_restart = True

    db.update_channel(channel_id, data)

    if needs_restart:
        from backend.channels.registry import channel_manager
        try:
            channel_manager.stop_channel(channel_id)
        except Exception as e:
            _logger.warning("stop_channel failed during restart for %s: %s", channel_id, e)
        try:
            channel_manager.start_channel(channel_id)
        except Exception as e:
            _logger.error("start_channel failed during restart for %s: %s", channel_id, e)

    return jsonify({'channel': _enriched_channel(db.get_channel(channel_id))})


@channels_bp.route('/api/channels/<channel_id>', methods=['DELETE'])
def api_delete_channel(channel_id):
    if not db.get_channel(channel_id):
        return jsonify({'error': 'Channel not found'}), 404
    from backend.channels.registry import channel_manager
    try:
        channel_manager.stop_channel(channel_id)
    except Exception as e:
        _logger.warning("stop_channel failed during delete for %s: %s", channel_id, e)
    db.delete_channel(channel_id)
    return jsonify({'success': True})


# ==================== JSON API: lifecycle ====================

@channels_bp.route('/api/channels/<channel_id>/start', methods=['POST'])
def api_start_channel(channel_id):
    if not db.get_channel(channel_id):
        return jsonify({'error': 'Channel not found'}), 404
    from backend.channels.registry import channel_manager
    try:
        channel_manager.start_channel(channel_id)
        return jsonify({'success': True, 'running': channel_manager.is_running(channel_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@channels_bp.route('/api/channels/<channel_id>/stop', methods=['POST'])
def api_stop_channel(channel_id):
    if not db.get_channel(channel_id):
        return jsonify({'error': 'Channel not found'}), 404
    from backend.channels.registry import channel_manager
    channel_manager.stop_channel(channel_id)
    return jsonify({'success': True, 'running': False})


@channels_bp.route('/api/channels/<channel_id>/restart', methods=['POST'])
def api_restart_channel(channel_id):
    if not db.get_channel(channel_id):
        return jsonify({'error': 'Channel not found'}), 404
    from backend.channels.registry import channel_manager
    try:
        channel_manager.stop_channel(channel_id)
    except Exception as e:
        _logger.warning("stop_channel failed during restart for %s: %s", channel_id, e)
    try:
        channel_manager.start_channel(channel_id)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'success': True, 'running': channel_manager.is_running(channel_id)})
