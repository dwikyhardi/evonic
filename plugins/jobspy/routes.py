"""Flask dashboard and APIs for the JobSpy plugin."""

import os

from flask import Blueprint, jsonify, render_template, request

from plugins.jobspy.cover_letter import CoverLetterError, generate_cover_letter
from plugins.jobspy.db import jobspy_db
from plugins.jobspy.service import (
    JobSpyOverlapError,
    JobSpyService,
    ProfileManager,
    ProfileValidationError,
)


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
REVIEW_STATUSES = {'new', 'saved', 'dismissed', 'applied'}


def _get_sdk():
    from backend.plugin_manager import plugin_manager
    from backend.plugin_sdk import PluginSDK
    return PluginSDK(
        'jobspy', plugin_manager.get_plugin_config('jobspy'), {},
        log_callback=plugin_manager.add_log,
    )


def _get_service(sdk):
    return JobSpyService(
        jobspy_db,
        timeout_seconds=sdk.config.get('SUBPROCESS_TIMEOUT_SECONDS', 180),
    )


def _manager():
    sdk = _get_sdk()
    return ProfileManager(jobspy_db, sdk, _get_service(sdk))


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ProfileValidationError('A JSON object is required')
    return data


def create_blueprint():
    bp = Blueprint(
        'jobspy', __name__,
        template_folder=os.path.join(PLUGIN_DIR, 'templates'),
    )

    @bp.route('/jobspy')
    def jobspy_page():
        return render_template('jobspy_cover_letter.html')

    @bp.route('/api/jobspy/summary')
    def api_summary():
        sdk = _get_sdk()
        summary = jobspy_db.summary(high_score=75)
        next_runs = [
            schedule.get('next_run_at') for schedule in sdk.list_schedules()
            if schedule.get('next_run_at')
        ]
        summary['next_run_at'] = min(next_runs) if next_runs else None
        return jsonify(summary)

    @bp.route('/api/jobspy/profiles', methods=['GET', 'POST'])
    def api_profiles():
        if request.method == 'GET':
            return jsonify({'profiles': jobspy_db.list_profiles()})
        try:
            profile = _manager().create_profile(_json_object())
            return jsonify({'profile': profile}), 201
        except ProfileValidationError as exc:
            return jsonify({'error': str(exc)}), 400

    @bp.route('/api/jobspy/profiles/<profile_id>', methods=['GET', 'PUT', 'DELETE'])
    def api_profile(profile_id):
        profile = jobspy_db.get_profile(profile_id)
        if not profile:
            return jsonify({'error': 'Search profile not found'}), 404
        if request.method == 'GET':
            return jsonify({'profile': profile})
        manager = _manager()
        if request.method == 'DELETE':
            manager.delete_profile(profile_id)
            return jsonify({'success': True})
        try:
            updated = manager.update_profile(profile_id, _json_object())
            return jsonify({'profile': updated})
        except ProfileValidationError as exc:
            return jsonify({'error': str(exc)}), 400

    @bp.route('/api/jobspy/profiles/<profile_id>/run', methods=['POST'])
    def api_run_profile(profile_id):
        if not jobspy_db.get_profile(profile_id):
            return jsonify({'error': 'Search profile not found'}), 404
        try:
            result = _manager().run_now(profile_id)
            return jsonify(result)
        except JobSpyOverlapError as exc:
            return jsonify({'error': str(exc)}), 409
        except ProfileValidationError as exc:
            return jsonify({'error': str(exc)}), 400

    @bp.route('/api/jobspy/jobs', methods=['GET', 'DELETE'])
    def api_jobs():
        if request.method == 'DELETE':
            return jsonify({
                'success': True,
                'cleared_jobs': jobspy_db.clear_jobs(),
            })
        min_score = request.args.get('min_score', type=int)
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        status = request.args.get('status') or None
        if status and status not in REVIEW_STATUSES:
            return jsonify({'error': 'Invalid review status'}), 400
        jobs = jobspy_db.list_jobs(
            profile_id=request.args.get('profile_id') or None,
            site=request.args.get('site') or None,
            review_status=status,
            min_score=min_score,
            search=request.args.get('search') or None,
            limit=limit,
            offset=offset,
        )
        return jsonify({'jobs': jobs, 'limit': limit, 'offset': offset})

    @bp.route('/api/jobspy/jobs/<job_id>/status', methods=['PATCH'])
    def api_job_status(job_id):
        data = request.get_json(silent=True) or {}
        status = data.get('status')
        if status not in REVIEW_STATUSES:
            return jsonify({'error': 'Invalid review status'}), 400
        job = jobspy_db.update_review_status(job_id, status)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify({'job': job})

    @bp.route('/api/jobspy/jobs/<job_id>/cover-letter', methods=['POST'])
    def api_job_cover_letter(job_id):
        job = jobspy_db.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        sdk = _get_sdk()
        try:
            from backend.llm_client import get_llm_client
            cover_letter = generate_cover_letter(
                job,
                sdk.config.get('PROFILE_TEXT', ''),
                get_llm_client(),
            )
            return jsonify({'cover_letter': cover_letter})
        except CoverLetterError as exc:
            return jsonify({'error': str(exc)}), exc.status_code

    @bp.route('/api/jobspy/runs')
    def api_runs():
        runs = jobspy_db.list_runs(
            profile_id=request.args.get('profile_id') or None,
            limit=request.args.get('limit', 50, type=int),
        )
        return jsonify({'runs': runs})

    return bp