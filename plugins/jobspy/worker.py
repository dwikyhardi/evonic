"""Narrow subprocess entry point for python-jobspy collection."""

import contextlib
import inspect
import json
import logging
import math
import sys
from datetime import date, datetime
from typing import Any, Callable, Dict


_SCRAPE_FIELDS = {
    'search_term', 'google_search_term', 'location', 'distance', 'is_remote',
    'job_type', 'easy_apply', 'results_wanted', 'country_indeed',
    'linkedin_fetch_description', 'hours_old',
}
_SITE_FIELDS = {
    'linkedin': {
        'search_term', 'location', 'distance', 'is_remote', 'job_type',
        'easy_apply', 'results_wanted', 'linkedin_fetch_description', 'hours_old',
    },
    'indeed': {
        'search_term', 'location', 'distance', 'is_remote', 'job_type',
        'easy_apply', 'results_wanted', 'country_indeed', 'hours_old',
    },
    'glassdoor': {
        'search_term', 'location', 'is_remote', 'job_type', 'easy_apply',
        'results_wanted', 'country_indeed', 'hours_old',
    },
    'google': {
        'google_search_term', 'location', 'results_wanted', 'hours_old',
    },
    'zip_recruiter': {
        'search_term', 'location', 'distance', 'is_remote', 'job_type',
        'results_wanted', 'hours_old',
    },
    'bayt': {'search_term', 'results_wanted'},
    'naukri': {
        'search_term', 'location', 'is_remote', 'results_wanted', 'hours_old',
    },
    'bdjobs': {'search_term', 'results_wanted'},
}
_LOGGER_NAMES = {
    'linkedin': {'LinkedIn', 'Linkedin'},
    'indeed': {'Indeed'},
    'glassdoor': {'Glassdoor'},
    'google': {'Google'},
    'zip_recruiter': {'ZipRecruiter', 'Zip_recruiter'},
    'bayt': {'Bayt'},
    'naukri': {'Naukri'},
    'bdjobs': {'BDJobs', 'Bdjobs'},
}


class _ErrorHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _jobspy_errors(site: str):
    handler = _ErrorHandler()
    loggers = [
        logging.getLogger(f'JobSpy:{name}')
        for name in _LOGGER_NAMES.get(site, {site.capitalize()})
    ]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        for logger in loggers:
            logger.removeHandler(handler)


@contextlib.contextmanager
def _bdjobs_compatibility(scrape_fn: Callable, site: str):
    """Bridge python-jobspy 1.1.82's BDJobs user_agent mismatch."""
    globals_map = getattr(scrape_fn, '__globals__', None)
    original = globals_map.get('BDJobs') if globals_map and site == 'bdjobs' else None
    if original is None or 'user_agent' in inspect.signature(original).parameters:
        yield
        return

    class CompatibleBDJobs(original):
        def __init__(self, proxies=None, ca_cert=None, user_agent=None):
            supported = inspect.signature(original).parameters
            kwargs = {
                key: value for key, value in {
                    'proxies': proxies,
                    'ca_cert': ca_cert,
                }.items() if key in supported
            }
            super().__init__(**kwargs)

    globals_map['BDJobs'] = CompatibleBDJobs
    try:
        yield
    finally:
        globals_map['BDJobs'] = original


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, 'item'):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    try:
        import pandas as pd
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (ImportError, TypeError, ValueError):
        pass
    return str(value)


def collect_jobs(request: Dict[str, Any], scrape_fn: Callable = None) -> Dict[str, Any]:
    """Collect sites independently so one board failure remains a partial run."""
    if scrape_fn is None:
        from jobspy import scrape_jobs
        scrape_fn = scrape_jobs

    sites = request.get('sites') or []
    jobs = []
    site_counts = {}
    errors = {}
    common = {
        key: value for key, value in request.items()
        if key in _SCRAPE_FIELDS and value is not None
    }
    common.setdefault('description_format', 'markdown')
    common.setdefault('verbose', 0)

    for site in sites:
        try:
            site_options = {
                key: value for key, value in common.items()
                if key in _SITE_FIELDS.get(site, set())
                or key in {'description_format', 'verbose'}
            }
            with _jobspy_errors(site) as logged_errors:
                with _bdjobs_compatibility(scrape_fn, site):
                    with contextlib.redirect_stdout(sys.stderr):
                        frame = scrape_fn(site_name=site, **site_options)
            records = frame.to_dict(orient='records') if frame is not None else []
            safe_records = [_json_safe(record) for record in records]
            for record in safe_records:
                record['site'] = str(record.get('site') or site).lower()
            jobs.extend(safe_records)
            site_counts[site] = len(safe_records)
            if logged_errors:
                errors[site] = '; '.join(dict.fromkeys(logged_errors))[:1000]
        except Exception as exc:
            site_counts[site] = 0
            errors[site] = str(exc)[:1000]

    return {'jobs': jobs, 'site_counts': site_counts, 'errors': errors}


def main() -> int:
    try:
        raw = sys.stdin.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Worker request exceeds 1 MB')
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError('Worker request must be a JSON object')
        result = collect_jobs(request)
        sys.stdout.write(json.dumps(result, separators=(',', ':'), default=str))
        return 0
    except Exception as exc:
        sys.stderr.write(f'JobSpy worker error: {str(exc)[:1000]}\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())