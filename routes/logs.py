import os
import re

from flask import Blueprint, jsonify, request

import config

logs_bp = Blueprint('logs', __name__)

LOGS_DIR = os.path.join(config.BASE_DIR, 'logs')


def _safe_path(relative):
    """Resolve a relative path and ensure it stays within LOGS_DIR."""
    if not relative or '..' in relative:
        return None
    full = os.path.realpath(os.path.join(LOGS_DIR, relative))
    if not full.startswith(os.path.realpath(LOGS_DIR) + os.sep) and full != os.path.realpath(LOGS_DIR):
        return None
    if not os.path.isfile(full):
        return None
    return full


def _human_size(nbytes):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}" if unit != 'B' else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _classify(name, rel_path):
    """Return a category string for grouping in the UI."""
    if 'sessrecap' in name:
        return 'sessrecap'
    base = os.path.basename(rel_path)
    mapping = {
        'evonic.log': 'system', 'agent.log': 'system',
        'channels.log': 'system', 'evaluator.log': 'system',
        'events.log': 'system',
    }
    for pattern, cat in mapping.items():
        if base == pattern or base.startswith(pattern.replace('.log', '.log.')):
            return cat
    return 'other'


@logs_bp.route('/api/logs/files')
def list_files():
    """List all log files with metadata."""
    files = []
    logs_real = os.path.realpath(LOGS_DIR)
    for root, _dirs, filenames in os.walk(LOGS_DIR):
        for fname in filenames:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, LOGS_DIR)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            files.append({
                'name': fname,
                'path': rel,
                'size': stat.st_size,
                'size_human': _human_size(stat.st_size),
                'modified': stat.st_mtime,
                'category': _classify(fname, rel),
            })
    files.sort(key=lambda f: (f['category'], f['path']))
    return jsonify(files)


@logs_bp.route('/api/logs/read')
def read_file():
    """Read log file content (tail by default)."""
    rel = request.args.get('file', '')
    full = _safe_path(rel)
    if not full:
        return jsonify({'error': 'Invalid file path'}), 400

    lines_count = min(int(request.args.get('lines', 500)), 5000)
    direction = request.args.get('direction', 'tail')

    try:
        file_size = os.path.getsize(full)
        with open(full, 'r', encoding='utf-8', errors='replace') as f:
            if direction == 'tail':
                # Efficient tail: estimate seek position
                avg_line = 120
                seek_pos = max(0, file_size - lines_count * avg_line)
                if seek_pos > 0:
                    f.seek(seek_pos)
                    f.readline()  # discard partial line
                all_lines = f.readlines()
                content = [l.rstrip('\n\r') for l in all_lines[-lines_count:]]
            else:
                content = []
                for i, line in enumerate(f):
                    if i >= lines_count:
                        break
                    content.append(line.rstrip('\n\r'))

        return jsonify({
            'content': content,
            'file_size': file_size,
            'file_size_human': _human_size(file_size),
            'total_lines': len(content),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@logs_bp.route('/api/logs/clear', methods=['POST'])
def clear_file():
    """Truncate a log file with a reset marker."""
    data = request.get_json(silent=True) or {}
    rel = data.get('file', '')
    full = _safe_path(rel)
    if not full:
        return jsonify({'error': 'Invalid file path'}), 400

    try:
        with open(full, 'w', encoding='utf-8') as f:
            f.write('---log-reset---\n')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@logs_bp.route('/api/logs/search')
def search_file():
    """Search within a log file."""
    rel = request.args.get('file', '')
    full = _safe_path(rel)
    if not full:
        return jsonify({'error': 'Invalid file path'}), 400

    query = request.args.get('query', '').lower()
    level_filter = request.args.get('level', '').upper()
    if not query and not level_filter:
        return jsonify({'error': 'Query or level required'}), 400

    results = []
    level_re = re.compile(r'^\[(\w+)\]')
    try:
        with open(full, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                line = line.rstrip('\n\r')
                if level_filter:
                    m = level_re.match(line)
                    if not m or m.group(1) != level_filter:
                        continue
                if query and query not in line.lower():
                    continue
                results.append({'line': i, 'text': line})
                if len(results) >= 500:
                    break
        return jsonify({'results': results, 'total': len(results)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
