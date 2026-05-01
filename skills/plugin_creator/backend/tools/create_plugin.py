"""
Plugin Creator tool — scaffolds a new Evonic plugin directory.
"""

import os
import re
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
PLUGINS_DIR = os.path.join(BASE_DIR, 'plugins')

VALID_EVENTS = {
    'turn_complete', 'message_received', 'session_created', 'summary_updated',
    'processing_started', 'llm_thinking', 'llm_response_chunk',
    'tool_executed', 'final_answer', 'message_sent',
}


def execute(agent: dict, args: dict) -> dict:
    plugin_id = args.get('id', '').strip()
    name = args.get('name', '').strip()
    description = args.get('description', '').strip()
    plugin_type = args.get('plugin_type', 'event_only')
    events = args.get('events', [])
    nav_label = args.get('nav_label', '').strip()
    nav_path = args.get('nav_path', '').strip() or f'/{plugin_id}'
    variables = args.get('variables', [])

    # Validate ID
    if not plugin_id:
        return {'status': 'error', 'message': 'id is required.'}
    if not re.match(r'^[a-zA-Z0-9_-]+$', plugin_id):
        return {'status': 'error', 'message': f'Invalid plugin id "{plugin_id}". Use only alphanumeric, dashes, and underscores.'}

    # Check for existing plugin
    plugin_dir = os.path.join(PLUGINS_DIR, plugin_id)
    if os.path.exists(plugin_dir):
        return {'status': 'error', 'message': f'Plugin "{plugin_id}" already exists at {plugin_dir}.'}

    # Validate events
    invalid_events = [e for e in events if e not in VALID_EVENTS]
    if invalid_events:
        return {'status': 'error', 'message': f'Unknown events: {invalid_events}. Valid: {sorted(VALID_EVENTS)}'}

    needs_handler = plugin_type in ('event_only', 'full')
    needs_routes = plugin_type in ('routes_only', 'full')
    has_nav = bool(nav_label) and needs_routes

    created_files = []

    try:
        os.makedirs(plugin_dir, exist_ok=True)
        if has_nav or needs_routes:
            os.makedirs(os.path.join(plugin_dir, 'templates'), exist_ok=True)

        # plugin.json
        manifest = {
            'id': plugin_id,
            'name': name,
            'version': '1.0.0',
            'description': description,
            'author': 'Evonic',
            'enabled': True,
        }
        if has_nav:
            manifest['nav_items'] = [{'label': nav_label, 'path': nav_path}]
        if needs_routes:
            routes_declared = [{'path': nav_path, 'methods': ['GET'], 'handler': 'page'}] if has_nav else []
            routes_declared.append({'path': f'/api/{plugin_id}', 'methods': ['GET', 'POST'], 'handler': 'api'})
            manifest['routes'] = routes_declared
        if needs_handler and events:
            manifest['events'] = events
        if variables:
            manifest['variables'] = variables

        _write_json(os.path.join(plugin_dir, 'plugin.json'), manifest)
        created_files.append('plugin.json')

        # handler.py
        if needs_handler:
            handler_lines = [
                f'"""\n{name} — event handlers.\n"""\n',
            ]
            if not events:
                handler_lines += [
                    '\n# No events subscribed yet.',
                    '# Add events to plugin.json and implement on_<event>(event, sdk) here.\n',
                ]
            else:
                for ev in events:
                    handler_lines += [
                        f'\ndef on_{ev}(event, sdk):',
                        f'    """Handle the {ev} event."""',
                        '    # TODO: implement handler logic',
                        '    sdk.log(f"on_{ev} called: {event}")\n',
                    ]
            _write_text(os.path.join(plugin_dir, 'handler.py'), '\n'.join(handler_lines))
            created_files.append('handler.py')
        else:
            # Minimal handler.py required by PluginManager to load the plugin
            _write_text(os.path.join(plugin_dir, 'handler.py'), f'"""\n{name} — no event handlers.\n"""\n')
            created_files.append('handler.py')

        # routes.py
        if needs_routes:
            routes_code = _generate_routes(plugin_id, name, nav_path, has_nav)
            _write_text(os.path.join(plugin_dir, 'routes.py'), routes_code)
            created_files.append('routes.py')

        # HTML template
        if has_nav:
            tmpl = _generate_template(plugin_id, name)
            _write_text(os.path.join(plugin_dir, 'templates', f'{plugin_id}.html'), tmpl)
            created_files.append(f'templates/{plugin_id}.html')

        # Empty config.json
        _write_json(os.path.join(plugin_dir, 'config.json'), {})
        created_files.append('config.json')

        # Hot-load the plugin
        from backend.plugin_manager import plugin_manager
        plugin_manager.reload_plugin(plugin_id)

        # Register blueprint with Flask if routes were created
        if needs_routes:
            try:
                from flask import current_app
                bp = plugin_manager.get_blueprints().get(plugin_id)
                if bp:
                    current_app.register_blueprint(bp)
            except RuntimeError:
                pass  # Outside app context — routes will be active on next request after reload

        return {
            'status': 'success',
            'plugin_id': plugin_id,
            'plugin_dir': plugin_dir,
            'created_files': created_files,
            'message': (
                f'Plugin "{plugin_id}" scaffolded successfully at plugins/{plugin_id}/. '
                f'Edit the generated files to add your logic.'
            ),
        }

    except Exception as e:
        # Clean up partial directory on failure
        import shutil
        if os.path.exists(plugin_dir):
            shutil.rmtree(plugin_dir, ignore_errors=True)
        return {'status': 'error', 'message': f'Failed to create plugin: {e}'}


def _write_json(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _write_text(path: str, content: str):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _generate_routes(plugin_id: str, name: str, nav_path: str, has_nav: bool) -> str:
    lines = [
        f'"""',
        f'{name} — Flask route handlers.',
        f'"""',
        '',
        'import os',
        'from flask import Blueprint, render_template, jsonify, request',
        '',
        f'PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))',
        '',
        '',
        'def create_blueprint():',
        f'    bp = Blueprint({repr(plugin_id)}, __name__,',
        f'                   template_folder=os.path.join(PLUGIN_DIR, "templates"))',
        '',
    ]
    if has_nav:
        lines += [
            f'    @bp.route({repr(nav_path)})',
            f'    def page():',
            f'        return render_template({repr(plugin_id + ".html")})',
            '',
        ]
    lines += [
        f'    @bp.route("/api/{plugin_id}", methods=["GET"])',
        f'    def api_get():',
        f'        # TODO: implement GET handler',
        f'        return jsonify({{"status": "ok", "plugin": {repr(plugin_id)}}})',
        '',
        f'    @bp.route("/api/{plugin_id}", methods=["POST"])',
        f'    def api_post():',
        f'        data = request.get_json() or {{}}',
        f'        # TODO: implement POST handler',
        f'        return jsonify({{"status": "ok", "received": data}})',
        '',
        '    return bp',
        '',
    ]
    return '\n'.join(lines)


def _generate_template(plugin_id: str, name: str) -> str:
    return f"""{{% extends "base.html" %}}
{{% block content %}}
<div class="p-4 md:p-6">
    <div class="flex items-center justify-between mb-6">
        <h1 class="text-xl font-semibold text-gray-900">{name}</h1>
    </div>

    <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <p class="text-gray-500 text-sm">Plugin <code>{plugin_id}</code> is ready. Edit
        <code>plugins/{plugin_id}/routes.py</code> and this template to add your UI.</p>
    </div>
</div>

<script>
    // TODO: add page logic here
</script>
{{% endblock %}}
"""
