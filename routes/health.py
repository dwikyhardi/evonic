"""Health check endpoint — used by the update supervisor for post-deploy validation."""
import time
import os

from flask import Blueprint, jsonify

health_bp = Blueprint('health', __name__)

_start_time = time.time()


def _get_version() -> str:
    version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'VERSION')
    try:
        with open(version_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return 'dev'


@health_bp.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'uptime': round(time.time() - _start_time, 1),
        'version': _get_version(),
    })
