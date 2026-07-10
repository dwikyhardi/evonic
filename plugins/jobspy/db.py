"""SQLite persistence for JobSpy profiles, runs, jobs, scores, and alerts."""

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_shared_data = os.path.join(BASE_DIR, 'shared', 'data')
_data_root = _shared_data if os.path.isdir(_shared_data) else os.path.join(BASE_DIR, 'data')
PLUGIN_DB_DIR = os.path.join(_data_root, 'db', 'plugins')
DB_PATH = os.path.join(PLUGIN_DB_DIR, 'jobspy.db')
SCHEMA_VERSION = 1

_TRACKING_PARAMS = {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_text(value: Any) -> str:
    return ' '.join(str(value or '').lower().split())


def canonical_job_url(value: Any) -> str:
    """Normalize a listing URL while retaining parameters that may identify a job."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {'http', 'https'} or not parts.netloc:
            return ''
        host = (parts.hostname or '').lower()
        port = parts.port
        if port and not ((parts.scheme.lower() == 'http' and port == 80)
                         or (parts.scheme.lower() == 'https' and port == 443)):
            host = f'{host}:{port}'
        query = [
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith('utm_') and key.lower() not in _TRACKING_PARAMS
        ]
        path = parts.path.rstrip('/') or '/'
        return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ''))
    except (TypeError, ValueError):
        return raw.rstrip('/')


def canonical_job_identity(job: Dict[str, Any]) -> str:
    """Return a stable identity from the source URL or title/company/location."""
    site = _normalized_text(job.get('site'))
    url = canonical_job_url(job.get('job_url'))
    if url:
        source = f'url|{site}|{url}'
    else:
        source = '|'.join((
            'fallback', site, _normalized_text(job.get('title')),
            _normalized_text(job.get('company')),
            _normalized_text(job.get('location')),
        ))
    return f'job_{hashlib.sha256(source.encode("utf-8")).hexdigest()}'


class JobSpyDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_tables()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_profiles (
                    id                TEXT PRIMARY KEY,
                    name              TEXT NOT NULL,
                    options_json      TEXT NOT NULL,
                    schedule_id       TEXT,
                    cadence_minutes   INTEGER NOT NULL DEFAULT 360,
                    enabled           INTEGER NOT NULL DEFAULT 1,
                    alert_threshold   INTEGER NOT NULL DEFAULT 75,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id        TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    started_at        TEXT NOT NULL,
                    finished_at       TEXT,
                    site_counts_json  TEXT NOT NULL DEFAULT '{}',
                    error_summary     TEXT,
                    timed_out         INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (profile_id) REFERENCES search_profiles(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id                TEXT PRIMARY KEY,
                    site              TEXT NOT NULL,
                    job_url           TEXT,
                    job_url_direct    TEXT,
                    title             TEXT NOT NULL,
                    company           TEXT,
                    location          TEXT,
                    description       TEXT,
                    job_type          TEXT,
                    is_remote         INTEGER NOT NULL DEFAULT 0,
                    date_posted       TEXT,
                    raw_json          TEXT NOT NULL,
                    first_seen_at     TEXT NOT NULL,
                    last_seen_at      TEXT NOT NULL,
                    review_status     TEXT NOT NULL DEFAULT 'new',
                    alerted_at        TEXT,
                    alert_error       TEXT,
                    alert_attempts    INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS job_matches (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id            TEXT NOT NULL,
                    run_id            INTEGER NOT NULL,
                    local_score       INTEGER NOT NULL,
                    model_score       INTEGER,
                    final_score       INTEGER NOT NULL,
                    reasons_json      TEXT NOT NULL,
                    scored_at         TEXT NOT NULL,
                    UNIQUE(job_id, run_id),
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_profiles_schedule ON search_profiles(schedule_id);
                CREATE INDEX IF NOT EXISTS idx_profiles_enabled ON search_profiles(enabled);
                CREATE INDEX IF NOT EXISTS idx_runs_profile_started ON scrape_runs(profile_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON scrape_runs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_review_status ON jobs(review_status);
                CREATE INDEX IF NOT EXISTS idx_jobs_alerted ON jobs(alerted_at);
                CREATE INDEX IF NOT EXISTS idx_matches_job_scored ON job_matches(job_id, scored_at DESC);
                CREATE INDEX IF NOT EXISTS idx_matches_final_score ON job_matches(final_score DESC);
            """)
            conn.execute(
                "INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()
            return int(row['value'])

    def table_names(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            return [row['name'] for row in rows]

    @staticmethod
    def _profile(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result['options'] = json.loads(result.pop('options_json'))
        result['enabled'] = bool(result['enabled'])
        result['min_score'] = result['alert_threshold']
        return result

    def create_profile(self, values: Dict[str, Any]) -> Dict[str, Any]:
        profile_id = str(values.get('id') or uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO search_profiles
                    (id, name, options_json, schedule_id, cadence_minutes, enabled,
                     alert_threshold, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile_id, str(values['name']).strip(),
                json.dumps(values.get('options') or {}, sort_keys=True),
                values.get('schedule_id'), int(values.get('cadence_minutes', 360)),
                1 if values.get('enabled', True) else 0,
                int(values.get('alert_threshold', 75)), now, now,
            ))
        return self.get_profile(profile_id)

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM search_profiles WHERE id=?', (profile_id,)
            ).fetchone()
            return self._profile(row)

    def list_profiles(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        sql = 'SELECT * FROM search_profiles'
        if enabled_only:
            sql += ' WHERE enabled=1'
        sql += ' ORDER BY name COLLATE NOCASE, created_at'
        with self._connect() as conn:
            return [self._profile(row) for row in conn.execute(sql).fetchall()]

    def get_profile_by_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM search_profiles WHERE schedule_id=?', (schedule_id,)
            ).fetchone()
            return self._profile(row)

    def update_profile(self, profile_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {
            'name': 'name', 'schedule_id': 'schedule_id',
            'cadence_minutes': 'cadence_minutes', 'enabled': 'enabled',
            'alert_threshold': 'alert_threshold', 'options': 'options_json',
        }
        assignments = []
        params: List[Any] = []
        for key, column in allowed.items():
            if key not in values:
                continue
            value = values[key]
            if key == 'options':
                value = json.dumps(value or {}, sort_keys=True)
            elif key == 'enabled':
                value = 1 if value else 0
            elif key in ('cadence_minutes', 'alert_threshold'):
                value = int(value)
            elif key == 'name':
                value = str(value).strip()
            assignments.append(f'{column}=?')
            params.append(value)
        if not assignments:
            return self.get_profile(profile_id)
        assignments.append('updated_at=?')
        params.extend((_now(), profile_id))
        with self._connect() as conn:
            cursor = conn.execute(
                f'UPDATE search_profiles SET {", ".join(assignments)} WHERE id=?', params
            )
            if cursor.rowcount == 0:
                return None
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute('DELETE FROM search_profiles WHERE id=?', (profile_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _run(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result['site_counts'] = json.loads(result.pop('site_counts_json'))
        result['timed_out'] = bool(result['timed_out'])
        return result

    def create_run(self, profile_id: str, started_at: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO scrape_runs(profile_id, status, started_at)
                VALUES (?, 'running', ?)
            """, (profile_id, started_at or _now()))
            run_id = cursor.lastrowid
        return self.get_run(run_id)

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            return self._run(conn.execute(
                'SELECT * FROM scrape_runs WHERE id=?', (run_id,)
            ).fetchone())

    def list_runs(self, profile_id: Optional[str] = None,
                  limit: int = 50) -> List[Dict[str, Any]]:
        sql = 'SELECT * FROM scrape_runs'
        params: List[Any] = []
        if profile_id:
            sql += ' WHERE profile_id=?'
            params.append(profile_id)
        sql += ' ORDER BY started_at DESC LIMIT ?'
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            return [self._run(row) for row in conn.execute(sql, params).fetchall()]

    def reconcile_running_runs(self, error_summary: str = 'Run interrupted before completion'
                               ) -> int:
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE scrape_runs
                SET status='failed', finished_at=?, error_summary=?
                WHERE status='running'
            """, (_now(), error_summary))
            return cursor.rowcount

    def finish_run(self, run_id: int, *, status: str,
                   site_counts: Optional[Dict[str, int]] = None,
                   error_summary: Optional[str] = None, timed_out: bool = False,
                   finished_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE scrape_runs
                SET status=?, finished_at=?, site_counts_json=?, error_summary=?, timed_out=?
                WHERE id=?
            """, (
                status, finished_at or _now(), json.dumps(site_counts or {}, sort_keys=True),
                error_summary, 1 if timed_out else 0, run_id,
            ))
            if cursor.rowcount == 0:
                return None
        return self.get_run(run_id)

    @staticmethod
    def _job(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result['raw'] = json.loads(result.pop('raw_json'))
        result['is_remote'] = bool(result['is_remote'])
        return result

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            return self._job(conn.execute(
                'SELECT * FROM jobs WHERE id=?', (job_id,)
            ).fetchone())

    def upsert_job(self, job: Dict[str, Any], seen_at: Optional[str] = None
                   ) -> Tuple[Dict[str, Any], bool]:
        job_id = canonical_job_identity(job)
        seen_at = seen_at or _now()
        canonical_url = canonical_job_url(job.get('job_url'))
        raw_json = json.dumps(job, sort_keys=True, default=str)
        with self._connect() as conn:
            exists = conn.execute('SELECT 1 FROM jobs WHERE id=?', (job_id,)).fetchone()
            conn.execute("""
                INSERT INTO jobs
                    (id, site, job_url, job_url_direct, title, company, location,
                     description, job_type, is_remote, date_posted, raw_json,
                     first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    site=excluded.site,
                    job_url=excluded.job_url,
                    job_url_direct=excluded.job_url_direct,
                    title=excluded.title,
                    company=excluded.company,
                    location=excluded.location,
                    description=excluded.description,
                    job_type=excluded.job_type,
                    is_remote=excluded.is_remote,
                    date_posted=excluded.date_posted,
                    raw_json=excluded.raw_json,
                    last_seen_at=excluded.last_seen_at
            """, (
                job_id, str(job.get('site') or '').lower(), canonical_url,
                job.get('job_url_direct'), str(job.get('title') or ''),
                job.get('company'), job.get('location'), job.get('description'),
                job.get('job_type'), 1 if job.get('is_remote') else 0,
                str(job.get('date_posted') or '') or None, raw_json, seen_at, seen_at,
            ))
        return self.get_job(job_id), exists is None

    @staticmethod
    def _match(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result['reasons'] = json.loads(result.pop('reasons_json'))
        return result

    def save_match(self, *, job_id: str, run_id: int, local_score: int,
                   model_score: Optional[int], final_score: int,
                   reasons: List[str]) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO job_matches
                    (job_id, run_id, local_score, model_score, final_score,
                     reasons_json, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, run_id) DO UPDATE SET
                    local_score=excluded.local_score,
                    model_score=excluded.model_score,
                    final_score=excluded.final_score,
                    reasons_json=excluded.reasons_json,
                    scored_at=excluded.scored_at
            """, (
                job_id, run_id, int(local_score),
                int(model_score) if model_score is not None else None,
                int(final_score), json.dumps(reasons), _now(),
            ))
            row = conn.execute(
                'SELECT * FROM job_matches WHERE job_id=? AND run_id=?',
                (job_id, run_id),
            ).fetchone()
            return self._match(row)

    def get_latest_match(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT * FROM job_matches
                WHERE job_id=?
                ORDER BY scored_at DESC, id DESC
                LIMIT 1
            """, (job_id,)).fetchone()
            return self._match(row)

    @staticmethod
    def _job_with_match(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result['raw'] = json.loads(result.pop('raw_json'))
        result['is_remote'] = bool(result['is_remote'])
        reasons_json = result.pop('reasons_json', None)
        result['reasons'] = json.loads(reasons_json) if reasons_json else []
        return result

    def list_jobs(self, *, profile_id: Optional[str] = None,
                  site: Optional[str] = None,
                  review_status: Optional[str] = None,
                  min_score: Optional[int] = None,
                  search: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> List[Dict[str, Any]]:
        match_profile_clause = ''
        params: List[Any] = []
        if profile_id:
            match_profile_clause = ' AND r2.profile_id=?'
            params.append(profile_id)
        sql = f"""
            SELECT j.*, m.local_score, m.model_score, m.final_score,
                   m.reasons_json, m.scored_at, r.profile_id AS match_profile_id
            FROM jobs j
            LEFT JOIN job_matches m ON m.id = (
                SELECT m2.id
                FROM job_matches m2
                JOIN scrape_runs r2 ON r2.id=m2.run_id
                WHERE m2.job_id=j.id{match_profile_clause}
                ORDER BY m2.scored_at DESC, m2.id DESC
                LIMIT 1
            )
            LEFT JOIN scrape_runs r ON r.id=m.run_id
            WHERE 1=1
        """
        if profile_id:
            sql += ' AND m.id IS NOT NULL'
        if site:
            sql += ' AND j.site=?'
            params.append(site.lower())
        if review_status:
            sql += ' AND j.review_status=?'
            params.append(review_status)
        if min_score is not None:
            sql += ' AND m.final_score>=?'
            params.append(int(min_score))
        if search:
            sql += " AND (j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)"
            pattern = f'%{search.strip()}%'
            params.extend((pattern, pattern, pattern))
        sql += ' ORDER BY COALESCE(m.final_score, -1) DESC, j.last_seen_at DESC LIMIT ? OFFSET ?'
        params.extend((max(1, min(int(limit), 500)), max(0, int(offset))))
        with self._connect() as conn:
            return [
                self._job_with_match(row)
                for row in conn.execute(sql, params).fetchall()
            ]

    def update_review_status(self, job_id: str, status: str) -> Optional[Dict[str, Any]]:
        if status not in {'new', 'saved', 'dismissed', 'applied'}:
            raise ValueError('Invalid review status')
        with self._connect() as conn:
            cursor = conn.execute(
                'UPDATE jobs SET review_status=? WHERE id=?', (status, job_id)
            )
            if cursor.rowcount == 0:
                return None
        return self.get_job(job_id)

    def clear_jobs(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute('DELETE FROM jobs')
            return cursor.rowcount

    def summary(self, high_score: int = 75) -> Dict[str, Any]:
        with self._connect() as conn:
            profile_counts = conn.execute("""
                SELECT COUNT(*) AS total, COALESCE(SUM(enabled), 0) AS enabled
                FROM search_profiles
            """).fetchone()
            job_counts = conn.execute("""
                WITH latest AS (
                    SELECT job_id, final_score,
                           ROW_NUMBER() OVER (
                               PARTITION BY job_id ORDER BY scored_at DESC, id DESC
                           ) AS position
                    FROM job_matches
                )
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN j.review_status='new'
                                         AND l.final_score>=? THEN 1 ELSE 0 END), 0) AS high
                FROM jobs j
                LEFT JOIN latest l ON l.job_id=j.id AND l.position=1
            """, (int(high_score),)).fetchone()
            partial_failures = conn.execute(
                "SELECT COUNT(*) AS count FROM scrape_runs WHERE status='partial'"
            ).fetchone()['count']
            last_row = conn.execute(
                'SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 1'
            ).fetchone()
            return {
                'profiles': profile_counts['total'],
                'enabled_profiles': profile_counts['enabled'],
                'jobs': job_counts['total'],
                'new_high_matches': job_counts['high'],
                'partial_failures': partial_failures,
                'last_run': self._run(last_row),
            }

    def record_alert_result(self, job_id: str, *, success: bool,
                            error: Optional[str] = None,
                            alerted_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE jobs
                SET alerted_at=CASE WHEN ? THEN ? ELSE alerted_at END,
                    alert_error=?,
                    alert_attempts=alert_attempts + 1
                WHERE id=?
            """, (
                1 if success else 0, (alerted_at or _now()) if success else None,
                None if success else (error or 'Alert delivery failed'), job_id,
            ))
            if cursor.rowcount == 0:
                return None
        return self.get_job(job_id)


jobspy_db = JobSpyDB()