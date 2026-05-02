"""
Caveman — Flask route handlers.
Dashboard + API endpoints for caveman mode management.
"""

import os
import sys
from flask import Blueprint, render_template, jsonify, request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_handler():
    """Find the already-loaded caveman handler module from sys.modules."""
    for name, mod in sys.modules.items():
        if name.endswith('.handler') and hasattr(mod, 'MODES') and hasattr(mod, '_agent_state'):
            # Verify it's the caveman handler by checking for CAVEMAN_RULES
            if hasattr(mod, 'CAVEMAN_RULES'):
                return mod
    raise RuntimeError("Caveman handler module not loaded. Enable the caveman plugin first.")


def create_blueprint():
    bp = Blueprint('caveman', __name__,
                   template_folder=os.path.join(PLUGIN_DIR, "templates"))

    @bp.route('/caveman')
    def page():
        return render_template('caveman.html')

    @bp.route("/api/caveman", methods=["GET"])
    def api_get():
        h = _find_handler()
        return jsonify({
            "status": "ok",
            "modes": list(h.MODES),
            "rules": h.CAVEMAN_RULES,
            "agents": {
                aid: {
                    "mode": s["mode"],
                    "turns": s["turns"],
                    "output_tokens": s["output_tokens"],
                    "input_tokens": s["input_tokens"],
                    "mode_switches": s["mode_switches"],
                }
                for aid, s in h._agent_state.items()
            },
            "lifetime": dict(h._lifetime_stats),
        })

    @bp.route("/api/caveman", methods=["POST"])
    def api_post():
        h = _find_handler()
        data = request.get_json() or {}

        action = data.get("action", "")

        if action == "set_mode":
            mode = data.get("mode", "full")
            agent_id = data.get("agent_id", "jeta")

            if mode not in h.MODES:
                return jsonify({"error": f"Unknown mode: {mode}", "valid_modes": list(h.MODES)}), 400

            s = h._get_agent_state(agent_id)
            s["mode"] = mode
            h._lifetime_stats["mode_switches"] += 1
            s["mode_switches"] += 1

            return jsonify({"status": "ok", "mode": mode, "agent_id": agent_id})

        elif action == "get_stats":
            return jsonify({
                "status": "ok",
                "lifetime": dict(h._lifetime_stats),
                "agents": {
                    aid: {
                        "mode": s["mode"],
                        "turns": s["turns"],
                        "output_tokens": s["output_tokens"],
                        "input_tokens": s["input_tokens"],
                    }
                    for aid, s in h._agent_state.items()
                },
            })

        elif action == "get_rules":
            mode = data.get("mode", "full")
            rules = h.CAVEMAN_RULES.get(mode, "")
            return jsonify({"status": "ok", "mode": mode, "rules": rules})

        return jsonify({"error": "Unknown action", "valid_actions": ["set_mode", "get_stats", "get_rules"]}), 400

    return bp
