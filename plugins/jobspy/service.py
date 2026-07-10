"""JobSpy validation, subprocess orchestration, persistence, and schedules."""

import copy
import json
import os
import subprocess
import sys
import threading
from typing import Any, Dict, Optional

from plugins.jobspy.db import JobSpyDB, jobspy_db
from plugins.jobspy.matcher import combine_scores, rerank_jobs, score_job


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUPPORTED_SITES = {
    'linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter',
    'bayt', 'naukri', 'bdjobs',
}
SITE_ALIASES = {
    'ziprecruiter': 'zip_recruiter',
    'zip-recruiter': 'zip_recruiter',
    'zip recruiter': 'zip_recruiter',
    'bd jobs': 'bdjobs',
    'bd_jobs': 'bdjobs',
}
JOB_TYPES = {'fulltime', 'parttime', 'internship', 'contract'}
INDEED_COUNTRIES = {
    'argentina', 'australia', 'austria', 'bahrain', 'bangladesh', 'belgium',
    'bulgaria', 'brazil', 'canada', 'chile', 'china', 'colombia', 'costa rica',
    'croatia', 'cyprus', 'czech republic', 'czechia', 'denmark', 'ecuador',
    'egypt', 'estonia', 'finland', 'france', 'germany', 'greece', 'hong kong',
    'hungary', 'india', 'indonesia', 'ireland', 'israel', 'italy', 'japan',
    'kuwait', 'latvia', 'lithuania', 'luxembourg', 'malaysia', 'malta',
    'mexico', 'morocco', 'netherlands', 'new zealand', 'nigeria', 'norway',
    'oman', 'pakistan', 'panama', 'peru', 'philippines', 'poland', 'portugal',
    'qatar', 'romania', 'saudi arabia', 'singapore', 'slovakia', 'slovenia',
    'south africa', 'south korea', 'spain', 'sweden', 'switzerland', 'taiwan',
    'thailand', 'türkiye', 'turkey', 'ukraine', 'united arab emirates', 'uk',
    'united kingdom', 'usa', 'us', 'united states', 'uruguay', 'venezuela',
    'vietnam',
}
GLASSDOOR_COUNTRIES = {
    'australia', 'austria', 'belgium', 'brazil', 'canada', 'france', 'germany',
    'hong kong', 'india', 'ireland', 'italy', 'mexico', 'netherlands',
    'new zealand', 'singapore', 'spain', 'switzerland', 'uk', 'united kingdom',
    'usa', 'us', 'united states',
}
_OPTION_FIELDS = {
    'sites', 'search_term', 'google_search_term', 'location', 'country_indeed',
    'distance', 'is_remote', 'job_type', 'easy_apply', 'results_wanted',
    'linkedin_fetch_description', 'hours_old',
}


class ProfileValidationError(ValueError):
    pass


class CollectionError(RuntimeError):
    pass


class CollectionTimeout(CollectionError):
    pass


class JobSpyOverlapError(RuntimeError):
    pass


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ProfileValidationError(f'{name} must be an integer')
    if parsed < minimum or parsed > maximum:
        raise ProfileValidationError(f'{name} must be between {minimum} and {maximum}')
    return parsed


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or '').strip()
    return text or None


def validate_profile(values: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a complete profile before storage or execution."""
    if not isinstance(values, dict):
        raise ProfileValidationError('Profile must be an object')
    name = _optional_text(values.get('name'))
    if not name:
        raise ProfileValidationError('Profile name is required')
    options = values.get('options')
    if not isinstance(options, dict):
        raise ProfileValidationError('JobSpy options must be an object')
    raw_sites = options.get('sites')
    if not isinstance(raw_sites, list) or not raw_sites:
        raise ProfileValidationError('At least one site is required')
    sites = []
    for raw_site in raw_sites:
        site = str(raw_site or '').strip().lower()
        site = SITE_ALIASES.get(site, site)
        if site not in SUPPORTED_SITES:
            raise ProfileValidationError(f'Unsupported JobSpy site: {raw_site}')
        if site not in sites:
            sites.append(site)

    search_term = _optional_text(options.get('search_term'))
    google_search_term = _optional_text(options.get('google_search_term'))
    non_google = [site for site in sites if site != 'google']
    if non_google and not search_term:
        raise ProfileValidationError('Search term is required for non-Google sites')
    if 'google' in sites and not google_search_term:
        raise ProfileValidationError('Google search term is required when Google is selected')
    if 'google' not in sites and google_search_term:
        raise ProfileValidationError('Google search term requires the Google site')

    normalized_options = {
        key: copy.deepcopy(value) for key, value in options.items()
        if key in _OPTION_FIELDS
    }
    normalized_options['sites'] = sites
    normalized_options['search_term'] = search_term
    normalized_options['google_search_term'] = google_search_term
    normalized_options['location'] = _optional_text(options.get('location'))
    country_indeed = (
        _optional_text(options.get('country_indeed')) or 'usa'
    ).lower()
    if {'indeed', 'glassdoor'} & set(sites) and country_indeed not in INDEED_COUNTRIES:
        raise ProfileValidationError(
            f'Unsupported Indeed country: {country_indeed}'
        )
    if 'glassdoor' in sites and country_indeed not in GLASSDOOR_COUNTRIES:
        raise ProfileValidationError(
            f'Glassdoor is not available for country: {country_indeed}'
        )
    normalized_options['country_indeed'] = country_indeed
    normalized_options['results_wanted'] = _bounded_int(
        options.get('results_wanted', 15), 'results_wanted', 1, 50
    )
    if options.get('hours_old') is not None:
        normalized_options['hours_old'] = _bounded_int(
            options['hours_old'], 'hours_old', 1, 24 * 30
        )
    else:
        normalized_options['hours_old'] = None
    if options.get('distance') is not None:
        normalized_options['distance'] = _bounded_int(
            options['distance'], 'distance', 1, 200
        )
    job_type = _optional_text(options.get('job_type'))
    if job_type:
        job_type = job_type.lower().replace('_', '').replace('-', '')
        if job_type not in JOB_TYPES:
            raise ProfileValidationError(f'Unsupported job type: {options.get("job_type")}')
    normalized_options['job_type'] = job_type
    normalized_options['is_remote'] = bool(options.get('is_remote', False))
    normalized_options['easy_apply'] = bool(options.get('easy_apply', False))
    normalized_options['linkedin_fetch_description'] = bool(
        options.get('linkedin_fetch_description', False)
    )

    score_field = 'min_score' if 'min_score' in values else 'alert_threshold'
    return {
        'name': name,
        'options': normalized_options,
        'schedule_id': values.get('schedule_id'),
        'cadence_minutes': _bounded_int(
            values.get('cadence_minutes', 360), 'cadence_minutes', 60, 7 * 24 * 60
        ),
        'enabled': bool(values.get('enabled', True)),
        'alert_threshold': _bounded_int(
            values.get(score_field, 75), score_field, 0, 100
        ),
    }


class JobSpyCollector:
    def __init__(self, popen_factory=subprocess.Popen):
        self._popen_factory = popen_factory

    def collect(self, request: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        process = self._popen_factory(
            [sys.executable, '-m', 'plugins.jobspy.worker'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=BASE_DIR,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(
                input=json.dumps(request, separators=(',', ':')),
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise CollectionTimeout(
                f'JobSpy worker timed out after {timeout_seconds} seconds'
            ) from exc

        if process.returncode != 0:
            detail = (stderr or 'no worker error output').strip()[-2000:]
            raise CollectionError(
                f'JobSpy worker exited with code {process.returncode}: {detail}'
            )
        try:
            result = json.loads(stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CollectionError('JobSpy worker returned invalid JSON') from exc
        if not isinstance(result, dict):
            raise CollectionError('JobSpy worker response must be an object')
        if not isinstance(result.get('jobs'), list):
            raise CollectionError('JobSpy worker response is missing jobs')
        if not isinstance(result.get('site_counts'), dict):
            raise CollectionError('JobSpy worker response is missing site counts')
        if not isinstance(result.get('errors'), dict):
            raise CollectionError('JobSpy worker response is missing errors')
        return result


class JobSpyService:
    _locks_guard = threading.Lock()
    _profile_locks: Dict[str, threading.Lock] = {}

    def __init__(self, database: JobSpyDB = jobspy_db, collector=None,
                 timeout_seconds: int = 180, llm_client=None):
        self.database = database
        self.collector = collector or JobSpyCollector()
        self.timeout_seconds = max(10, min(int(timeout_seconds), 900))
        self.llm_client = llm_client

    @classmethod
    def _lock_for(cls, profile_id: str) -> threading.Lock:
        with cls._locks_guard:
            return cls._profile_locks.setdefault(profile_id, threading.Lock())

    def run_profile(self, profile_id: str, sdk=None) -> Dict[str, Any]:
        profile = self.database.get_profile(profile_id)
        if not profile:
            raise ProfileValidationError('Search profile not found')
        profile = validate_profile(profile)
        lock = self._lock_for(profile_id)
        if not lock.acquire(blocking=False):
            raise JobSpyOverlapError('A run is already active for this profile')

        run = None
        try:
            run = self.database.create_run(profile_id)
            try:
                result = self.collector.collect(profile['options'], self.timeout_seconds)
                persisted = []
                malformed = 0
                for raw_job in result['jobs']:
                    if not isinstance(raw_job, dict) or not raw_job.get('title'):
                        malformed += 1
                        continue
                    job, created = self.database.upsert_job(raw_job)
                    job['is_new'] = created
                    persisted.append(job)
                errors = dict(result['errors'])
                if malformed:
                    errors['normalization'] = f'Ignored {malformed} malformed job record(s)'
                status = 'partial' if errors else 'success'
                error_summary = '; '.join(
                    f'{site}: {error}' for site, error in sorted(errors.items())
                ) or None
                completed = self.database.finish_run(
                    run['id'], status=status, site_counts=result['site_counts'],
                    error_summary=error_summary,
                )
                matches = self._score_and_alert(
                    profile, run['id'], persisted, sdk=sdk
                )
                return {'run': completed, 'jobs': persisted, 'matches': matches}
            except CollectionTimeout as exc:
                completed = self.database.finish_run(
                    run['id'], status='timeout', error_summary=str(exc), timed_out=True
                )
                return {'run': completed, 'jobs': [], 'matches': []}
            except Exception as exc:
                completed = self.database.finish_run(
                    run['id'], status='failed', error_summary=str(exc)[:2000]
                )
                return {'run': completed, 'jobs': [], 'matches': []}
        finally:
            lock.release()

    @staticmethod
    def _config(sdk, name: str, default: Any) -> Any:
        return sdk.config.get(name, default) if sdk and hasattr(sdk, 'config') else default

    def _score_and_alert(self, profile: Dict[str, Any], run_id: int,
                         jobs: list, sdk=None) -> list:
        profile_text = str(self._config(sdk, 'PROFILE_TEXT', '') or '')
        exclusion_text = str(self._config(sdk, 'EXCLUSION_TERMS', '') or '')
        exclusion_terms = [
            term.strip() for term in exclusion_text.replace('\n', ',').split(',')
            if term.strip()
        ]
        local_results = {}
        for job in jobs:
            local_results[job['id']] = score_job(
                profile_text,
                job,
                preferred_remote=bool(profile['options'].get('is_remote')),
                preferred_job_type=profile['options'].get('job_type'),
                exclusion_terms=exclusion_terms,
            )

        local_threshold = max(0, min(100, int(
            self._config(sdk, 'LOCAL_SCORE_THRESHOLD', 55)
        )))
        top_n = max(0, min(50, int(self._config(sdk, 'RERANK_TOP_N', 20))))
        candidates = sorted(
            (job for job in jobs if local_results[job['id']].local_score >= local_threshold),
            key=lambda job: (-local_results[job['id']].local_score, job['id']),
        )[:top_n]
        model_results = {}
        rerank_enabled = bool(self._config(sdk, 'RERANK_ENABLED', True))
        if rerank_enabled and candidates and profile_text:
            client = self.llm_client
            if client is None:
                try:
                    from backend.llm_client import LLMClient
                    client = LLMClient()
                except Exception:
                    client = None
            model_results = rerank_jobs(profile_text, candidates, client)

        matches = []
        for job in jobs:
            model = model_results.get(job['id'])
            result = combine_scores(
                local_results[job['id']],
                model.get('score') if model else None,
                model.get('reason') if model else None,
            )
            stored = self.database.save_match(
                job_id=job['id'], run_id=run_id,
                local_score=result.local_score,
                model_score=result.model_score,
                final_score=result.final_score,
                reasons=result.reasons,
            )
            matches.append(stored)
            if result.final_score >= profile['alert_threshold']:
                self._alert(job, result, sdk)
        return matches

    def _alert(self, job: Dict[str, Any], match, sdk=None) -> None:
        current = self.database.get_job(job['id'])
        if not current or current.get('alerted_at'):
            return
        agent_id = str(self._config(sdk, 'ALERT_AGENT_ID', '') or '').strip()
        external_user_id = str(
            self._config(sdk, 'ALERT_EXTERNAL_USER_ID', '') or ''
        ).strip()
        channel_id = str(self._config(sdk, 'ALERT_CHANNEL_ID', '') or '').strip()
        if not sdk or not all((agent_id, external_user_id, channel_id)):
            self.database.record_alert_result(
                job['id'], success=False, error='Alert routing is not fully configured'
            )
            return

        reasons = '; '.join(match.reasons[:4]) or 'Profile match'
        link = current.get('job_url_direct') or current.get('job_url') or 'No source URL'
        message = (
            f'New JobSpy match — {match.final_score}/100\n'
            f'{current.get("title") or "Untitled role"} at '
            f'{current.get("company") or "Unknown company"}\n'
            f'Location: {current.get("location") or "Not listed"}\n'
            f'Source: {current.get("site") or "unknown"}\n'
            f'Reasons: {reasons}\n'
            f'{link}'
        )
        try:
            delivery = sdk.send_message(
                agent_id, external_user_id, channel_id, message
            )
            success = bool(delivery and delivery.get('success'))
            error = None if success else str(
                (delivery or {}).get('error') or 'Alert delivery failed'
            )[:1000]
        except Exception as exc:
            success = False
            error = str(exc)[:1000]
        self.database.record_alert_result(
            job['id'], success=success, error=error
        )


class ProfileManager:
    def __init__(self, database: JobSpyDB, sdk, runner: JobSpyService):
        self.database = database
        self.sdk = sdk
        self.runner = runner

    def _create_schedule(self, profile: Dict[str, Any]) -> str:
        schedule = self.sdk.create_schedule(
            name=f'JobSpy: {profile["name"]}',
            trigger_type='interval',
            trigger_config={'minutes': profile['cadence_minutes']},
            action_type='emit_event',
            action_config={
                'event_name': 'jobspy_profile_due',
                'payload': {'profile_id': profile['id']},
            },
            metadata={'profile_id': profile['id']},
        )
        return schedule['id']

    def create_profile(self, values: Dict[str, Any]) -> Dict[str, Any]:
        clean = validate_profile(values)
        clean['schedule_id'] = None
        profile = self.database.create_profile(clean)
        if not profile['enabled']:
            return profile
        try:
            schedule_id = self._create_schedule(profile)
        except Exception:
            self.database.delete_profile(profile['id'])
            raise
        return self.database.update_profile(profile['id'], {'schedule_id': schedule_id})

    def update_profile(self, profile_id: str, changes: Dict[str, Any]
                       ) -> Optional[Dict[str, Any]]:
        current = self.database.get_profile(profile_id)
        if not current:
            return None
        changes = dict(changes)
        if 'min_score' in changes:
            changes['alert_threshold'] = changes['min_score']
        elif 'alert_threshold' in changes:
            changes['min_score'] = changes['alert_threshold']
        proposed = dict(current)
        proposed.update(changes)
        clean = validate_profile(proposed)
        old_schedule_id = current.get('schedule_id')
        schedule_changed = any(
            key in changes for key in ('name', 'cadence_minutes', 'enabled')
        )
        new_schedule_id = old_schedule_id
        if not clean['enabled']:
            new_schedule_id = None
        elif not old_schedule_id or schedule_changed:
            schedule_profile = dict(current)
            schedule_profile.update(clean)
            schedule_profile['id'] = profile_id
            new_schedule_id = self._create_schedule(schedule_profile)

        clean['schedule_id'] = new_schedule_id
        updated = self.database.update_profile(profile_id, clean)
        if old_schedule_id and old_schedule_id != new_schedule_id:
            self.sdk.cancel_schedule(old_schedule_id)
        return updated

    def delete_profile(self, profile_id: str) -> bool:
        profile = self.database.get_profile(profile_id)
        if not profile:
            return False
        if profile.get('schedule_id'):
            self.sdk.cancel_schedule(profile['schedule_id'])
        return self.database.delete_profile(profile_id)

    def run_now(self, profile_id: str) -> Dict[str, Any]:
        if not self.database.get_profile(profile_id):
            raise ProfileValidationError('Search profile not found')
        return self.runner.run_profile(profile_id, sdk=self.sdk)