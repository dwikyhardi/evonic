"""
Auto Improver — Flask route handlers.
"""

import os
from flask import Blueprint, render_template, jsonify, request
from . import analysis

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def create_blueprint():
    bp = Blueprint('auto_improver', __name__,
                   template_folder=os.path.join(PLUGIN_DIR, "templates"))

    @bp.route("/auto_improver")
    def dashboard():
        """Dashboard page showing recent analyses and agent performance."""
        recent_analyses = analysis.get_recent_analyses(limit=20)
        # Strip stored_messages from any legacy entries before passing to template
        for a in recent_analyses:
            a.pop('stored_messages', None)
        return render_template("auto_improver.html", analyses=recent_analyses)

    @bp.route("/api/auto_improver/analyze", methods=["POST"])
    def analyze_session():
        """Trigger manual re-analysis on a previously analyzed session."""
        data = request.get_json() or {}
        session_id = data.get("session_id")
        agent_id = data.get("agent_id", "")

        if not session_id:
            return jsonify({"error": "session_id is required"}), 400

        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400

        # Load messages from the separate cache
        cache = analysis.load_messages_cache()
        stored_messages = cache.get(session_id)
        if not stored_messages:
            return jsonify({
                "error": "No messages cached for this session. Auto-analysis must run first to populate the cache."
            }), 404

        result = analysis.analyze_session(session_id, agent_id, stored_messages)
        analysis.save_analysis_result(result)

        return jsonify({"status": "ok", "result": result})

    @bp.route("/api/auto_improver/results", methods=["GET"])
    def get_results():
        """Get analysis results."""
        limit = int(request.args.get("limit", 10))
        analyses = analysis.get_recent_analyses(limit=limit)
        return jsonify({"status": "ok", "analyses": analyses})

    @bp.route("/api/auto_improver/sessions", methods=["GET"])
    def get_sessions():
        """List sessions with analysis results."""
        data = analysis.load_results()
        sessions = data.get("sessions", {})
        return jsonify({"status": "ok", "sessions": sessions})

    @bp.route("/api/auto_improver/agent/<agent_id>", methods=["GET"])
    def get_agent_performance(agent_id):
        """Get performance summary for an agent."""
        performance = analysis.get_agent_performance(agent_id)
        return jsonify({"status": "ok", "performance": performance})

    @bp.route("/api/auto_improver/session/<session_id>", methods=["GET"])
    def get_session_analysis(session_id):
        """Get all analyses for a specific session."""
        session_analyses = analysis.get_session_analysis(session_id)
        return jsonify({"status": "ok", "analyses": session_analyses})

    @bp.route("/api/auto_improver", methods=["GET"])
    def api_get():
        return jsonify({"status": "ok", "plugin": 'auto_improver'})

    @bp.route("/api/auto_improver", methods=["POST"])
    def api_post():
        data = request.get_json() or {}
        return jsonify({"status": "ok", "received": data})

    return bp
