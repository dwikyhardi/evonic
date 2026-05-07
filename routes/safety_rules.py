"""REST API for HMADS custom safety rules (CRUD) and agent rule assignments."""

from flask import Blueprint, jsonify, request

from models.db import db

safety_rules_bp = Blueprint('safety_rules', __name__)


@safety_rules_bp.route('/api/safety-rules', methods=['GET'])
def api_list_rules():
    """List all safety rules."""
    enabled_only = request.args.get('enabled_only', '').lower() in ('1', 'true')
    rules = db.get_safety_rules(enabled_only=enabled_only)
    return jsonify({'rules': rules})


@safety_rules_bp.route('/api/safety-rules/<rule_id>', methods=['GET'])
def api_get_rule(rule_id):
    rule = db.get_safety_rule(rule_id)
    if not rule:
        return jsonify({'error': 'Rule not found'}), 404
    return jsonify(rule)


@safety_rules_bp.route('/api/safety-rules', methods=['POST'])
def api_create_rule():
    data = request.get_json(silent=True) or {}
    required = ('name', 'pattern', 'category')
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate regex
    import re
    try:
        re.compile(data['pattern'])
    except re.error as exc:
        return jsonify({'error': f'Invalid regex pattern: {exc}'}), 400

    # Validate weight range
    weight = data.get('weight', 5)
    try:
        weight = int(weight)
        if not 1 <= weight <= 20:
            return jsonify({'error': 'Weight must be between 1 and 20'}), 400
        data['weight'] = weight
    except (TypeError, ValueError):
        return jsonify({'error': 'Weight must be an integer'}), 400

    # Validate tool_scope
    tool_scope = data.get('tool_scope', 'all')
    if tool_scope not in ('all', 'python', 'bash'):
        return jsonify({'error': 'tool_scope must be one of: all, python, bash'}), 400

    # Validate scope
    scope = data.get('scope', 'global')
    if scope not in ('global', 'specific'):
        return jsonify({'error': 'scope must be one of: global, specific'}), 400

    rule_id = db.create_safety_rule(data)
    _invalidate_checker_cache()
    return jsonify({'id': rule_id, 'message': 'Rule created'}), 201


@safety_rules_bp.route('/api/safety-rules/<rule_id>', methods=['PUT'])
def api_update_rule(rule_id):
    existing = db.get_safety_rule(rule_id)
    if not existing:
        return jsonify({'error': 'Rule not found'}), 404
    if existing.get('is_system'):
        return jsonify({'error': 'System rules cannot be modified'}), 403

    data = request.get_json(silent=True) or {}

    # Validate regex if provided
    if 'pattern' in data:
        import re
        try:
            re.compile(data['pattern'])
        except re.error as exc:
            return jsonify({'error': f'Invalid regex pattern: {exc}'}), 400

    # Validate weight if provided
    if 'weight' in data:
        try:
            w = int(data['weight'])
            if not 1 <= w <= 20:
                return jsonify({'error': 'Weight must be between 1 and 20'}), 400
            data['weight'] = w
        except (TypeError, ValueError):
            return jsonify({'error': 'Weight must be an integer'}), 400

    # Validate scope if provided
    if 'scope' in data and data['scope'] not in ('global', 'specific'):
        return jsonify({'error': 'scope must be one of: global, specific'}), 400

    ok = db.update_safety_rule(rule_id, data)
    if ok:
        _invalidate_checker_cache()
    return jsonify({'updated': ok})


@safety_rules_bp.route('/api/safety-rules/<rule_id>', methods=['DELETE'])
def api_delete_rule(rule_id):
    existing = db.get_safety_rule(rule_id)
    if not existing:
        return jsonify({'error': 'Rule not found'}), 404
    if existing.get('is_system'):
        return jsonify({'error': 'System rules cannot be deleted'}), 403
    ok = db.delete_safety_rule(rule_id)
    if ok:
        _invalidate_checker_cache()
    return jsonify({'deleted': ok})


@safety_rules_bp.route('/api/safety-rules/test', methods=['POST'])
def api_test_rule():
    """Test a regex pattern against sample code without saving."""
    data = request.get_json(silent=True) or {}
    pattern = data.get('pattern', '')
    code = data.get('code', '')
    if not pattern:
        return jsonify({'error': 'pattern is required'}), 400

    import re
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return jsonify({'error': f'Invalid regex: {exc}', 'matches': False}), 400

    match = compiled.search(code)
    return jsonify({
        'matches': bool(match),
        'match_text': match.group(0) if match else None,
        'match_start': match.start() if match else None,
        'match_end': match.end() if match else None,
    })


# ---- Agent ↔ Rule assignments ----

@safety_rules_bp.route('/api/agents/<agent_id>/safety-rules', methods=['GET'])
def api_get_agent_rules(agent_id):
    """Get rule IDs assigned to this agent."""
    rule_ids = db.get_agent_safety_rules(agent_id)
    return jsonify({'rule_ids': rule_ids})


@safety_rules_bp.route('/api/agents/<agent_id>/safety-rules', methods=['PUT'])
def api_set_agent_rules(agent_id):
    """Set the safety rules assigned to this agent (replaces all)."""
    data = request.get_json(silent=True) or {}
    rule_ids = data.get('rule_ids', [])
    if not isinstance(rule_ids, list):
        return jsonify({'error': 'rule_ids must be an array'}), 400
    db.set_agent_safety_rules(agent_id, rule_ids)
    _invalidate_checker_cache()
    return jsonify({'updated': True})


def _invalidate_checker_cache():
    """Invalidate the CustomRuleChecker cache after DB changes."""
    try:
        from backend.tools.lib.custom_rule_checker import custom_rule_checker
        custom_rule_checker.invalidate_cache()
    except Exception:
        pass
