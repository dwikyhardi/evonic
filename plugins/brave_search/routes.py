"""Brave Search — Flask route handlers."""

import os
import requests
from flask import Blueprint, jsonify, request

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


def _load_config():
    cfg_path = os.path.join(PLUGIN_DIR, "config.json")
    if os.path.exists(cfg_path):
        import json
        with open(cfg_path) as f:
            return json.load(f)
    return {}


def create_blueprint():
    bp = Blueprint('brave_search', __name__,
                   template_folder=os.path.join(PLUGIN_DIR, "templates"))

    @bp.route("/brave/search", methods=["GET", "POST"])
    def search():
        cfg = _load_config()
        api_key = cfg.get("BRAVE_API_KEY", "")
        if not api_key:
            return jsonify({"error": "BRAVE_API_KEY not configured"}), 500

        if request.method == "POST":
            data = request.get_json() or {}
        else:
            data = request.args.to_dict()

        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "query param required"}), 400

        count = min(int(data.get("count", 10)), 20)

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {"q": query, "count": count}

        try:
            resp = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            return jsonify({"error": f"Brave API request failed: {str(e)}"}), 502

        results = []
        for r in raw.get("web", {}).get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            })

        return jsonify({
            "query": query,
            "count": len(results),
            "results": results,
        })

    return bp
