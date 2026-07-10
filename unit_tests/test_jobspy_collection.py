"""Collection, validation, and scheduling tests for the JobSpy plugin."""

import json
import logging
import subprocess
from unittest.mock import MagicMock

import pytest

from plugins.jobspy.db import JobSpyDB


def _profile(**overrides):
    values = {
        "name": "Flutter jobs",
        "options": {
            "sites": ["linkedin", "indeed"],
            "search_term": "Flutter developer",
            "location": "Indonesia",
            "country_indeed": "indonesia",
            "results_wanted": 20,
            "hours_old": 72,
            "job_type": "contract",
            "is_remote": True,
        },
        "cadence_minutes": 180,
        "alert_threshold": 80,
        "enabled": True,
    }
    values.update(overrides)
    return values


def _job(site="linkedin", url="https://example.com/jobs/1"):
    return {
        "site": site,
        "job_url": url,
        "title": "Flutter Developer",
        "company": "Example",
        "location": "Remote",
        "description": "Flutter and Dart",
        "is_remote": True,
    }


def test_profile_validation_normalizes_aliases_and_rejects_bad_combinations():
    from plugins.jobspy.service import ProfileValidationError, validate_profile

    valid = _profile()
    valid["options"]["sites"] = ["LinkedIn", "ziprecruiter"]
    normalized = validate_profile(valid)
    assert normalized["options"]["sites"] == ["linkedin", "zip_recruiter"]

    invalid_cases = [
        _profile(options={"sites": [], "search_term": "Flutter"}),
        _profile(options={"sites": ["unsupported"], "search_term": "Flutter"}),
        _profile(options={"sites": ["google"], "search_term": "Flutter"}),
        _profile(options={"sites": ["linkedin"], "search_term": "Flutter",
                          "google_search_term": "Flutter jobs"}),
        _profile(options={"sites": ["linkedin"], "search_term": "Flutter",
                          "results_wanted": 1000}),
        _profile(options={"sites": ["linkedin"], "search_term": "Flutter",
                          "job_type": "temporary"}),
        _profile(options={"sites": ["indeed"], "search_term": "Flutter",
                          "country_indeed": "worldwide"}),
        _profile(options={"sites": ["glassdoor"], "search_term": "Flutter",
                          "country_indeed": "indonesia"}),
        _profile(cadence_minutes=5),
        _profile(alert_threshold=101),
    ]
    for invalid in invalid_cases:
        with pytest.raises(ProfileValidationError):
            validate_profile(invalid)


def test_worker_collects_each_site_with_supported_options_and_serializes_values():
    pd = pytest.importorskip("pandas")
    from plugins.jobspy.worker import collect_jobs

    calls = []

    def scrape_fn(**kwargs):
        calls.append(kwargs)
        if kwargs["site_name"] == "indeed":
            raise RuntimeError("429 rate limited")
        return pd.DataFrame([{
            "site": kwargs["site_name"],
            "job_url": f"https://example.com/{kwargs['site_name']}/1",
            "title": "Flutter Developer",
            "company": "Example",
            "date_posted": pd.Timestamp("2026-07-10T10:00:00Z"),
            "min_amount": float("nan"),
            "salary_source": pd.NA,
        }])

    result = collect_jobs({
        "sites": ["linkedin", "indeed", "bayt", "bdjobs"],
        "search_term": "Flutter",
        "location": "Indonesia",
        "country_indeed": "indonesia",
        "is_remote": True,
        "hours_old": 72,
        "linkedin_fetch_description": True,
        "results_wanted": 10,
    }, scrape_fn=scrape_fn)

    assert [call["site_name"] for call in calls] == [
        "linkedin", "indeed", "bayt", "bdjobs"
    ]
    assert result["site_counts"] == {
        "linkedin": 1, "indeed": 0, "bayt": 1, "bdjobs": 1
    }
    assert result["errors"] == {"indeed": "429 rate limited"}
    assert result["jobs"][0]["date_posted"] == "2026-07-10T10:00:00+00:00"
    assert result["jobs"][0]["min_amount"] is None
    assert result["jobs"][0]["salary_source"] is None
    bayt_call = next(call for call in calls if call["site_name"] == "bayt")
    assert set(bayt_call) == {
        "site_name", "search_term", "results_wanted", "description_format", "verbose"
    }
    bdjobs_call = next(call for call in calls if call["site_name"] == "bdjobs")
    assert set(bdjobs_call) == {
        "site_name", "search_term", "results_wanted", "description_format", "verbose"
    }


def test_worker_supports_jobspy_bdjobs_without_user_agent_constructor():
    pd = pytest.importorskip("pandas")
    from plugins.jobspy.worker import collect_jobs

    class LegacyBDJobs:
        def __init__(self, proxies=None, ca_cert=None):
            self.proxies = proxies

    namespace = {"BDJobs": LegacyBDJobs, "pd": pd}
    exec(
        "def scrape_fn(**kwargs):\n"
        "    BDJobs(proxies=None, ca_cert=None, user_agent=None)\n"
        "    return pd.DataFrame([{'title': 'Flutter Developer'}])",
        namespace,
    )

    result = collect_jobs({
        "sites": ["bdjobs"],
        "search_term": "Flutter",
        "results_wanted": 10,
    }, scrape_fn=namespace["scrape_fn"])

    assert result["site_counts"] == {"bdjobs": 1}
    assert result["errors"] == {}
    assert result["jobs"][0]["site"] == "bdjobs"


def test_worker_records_jobspy_logged_board_errors():
    pd = pytest.importorskip("pandas")
    from plugins.jobspy.worker import collect_jobs

    def scrape_fn(**kwargs):
        logging.getLogger("JobSpy:Bayt").error("403 Client Error: Forbidden")
        return pd.DataFrame()

    result = collect_jobs({
        "sites": ["bayt"],
        "search_term": "Flutter",
        "results_wanted": 10,
    }, scrape_fn=scrape_fn)

    assert result["site_counts"] == {"bayt": 0}
    assert result["errors"] == {"bayt": "403 Client Error: Forbidden"}


class _Process:
    def __init__(self, stdout="", stderr="", returncode=0, timeout=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.terminated = False
        self.killed = False

    def communicate(self, input=None, timeout=None):
        if self.timeout and not self.terminated:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self._stdout, self._stderr

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


def test_collector_handles_success_nonzero_malformed_and_timeout():
    from plugins.jobspy.service import (
        CollectionError,
        CollectionTimeout,
        JobSpyCollector,
    )

    payload = {"jobs": [], "site_counts": {"linkedin": 0}, "errors": {}}
    process = _Process(stdout=json.dumps(payload))
    collector = JobSpyCollector(popen_factory=MagicMock(return_value=process))
    assert collector.collect({"sites": ["linkedin"]}, 10) == payload

    for bad_process in (
        _Process(stderr="worker failed", returncode=2),
        _Process(stdout="not-json"),
    ):
        with pytest.raises(CollectionError):
            JobSpyCollector(
                popen_factory=MagicMock(return_value=bad_process)
            ).collect({"sites": ["linkedin"]}, 10)

    timed_out = _Process(timeout=True)
    with pytest.raises(CollectionTimeout):
        JobSpyCollector(
            popen_factory=MagicMock(return_value=timed_out)
        ).collect({"sites": ["linkedin"]}, 1)
    assert timed_out.terminated is True


class _Collector:
    def __init__(self, result=None, error=None, before_return=None):
        self.result = result or {"jobs": [], "site_counts": {}, "errors": {}}
        self.error = error
        self.before_return = before_return

    def collect(self, request, timeout_seconds):
        if self.before_return:
            self.before_return()
        if self.error:
            raise self.error
        return self.result


def test_service_persists_success_partial_empty_and_failure(tmp_path):
    from plugins.jobspy.service import CollectionError, CollectionTimeout, JobSpyService

    scenarios = [
        ({"jobs": [_job()], "site_counts": {"linkedin": 1}, "errors": {}},
         "success"),
        ({"jobs": [_job()], "site_counts": {"linkedin": 1, "indeed": 0},
          "errors": {"indeed": "429"}}, "partial"),
        ({"jobs": [], "site_counts": {"linkedin": 0}, "errors": {}},
         "success"),
    ]
    for index, (result, expected_status) in enumerate(scenarios):
        database = JobSpyDB(str(tmp_path / f"service-{index}.db"))
        profile = database.create_profile(_profile())
        outcome = JobSpyService(database, _Collector(result)).run_profile(profile["id"])
        assert outcome["run"]["status"] == expected_status
        assert outcome["run"]["site_counts"] == result["site_counts"]
        assert len(outcome["jobs"]) == len(result["jobs"])

    database = JobSpyDB(str(tmp_path / "failure.db"))
    profile = database.create_profile(_profile())
    outcome = JobSpyService(
        database, _Collector(error=CollectionError("invalid worker output"))
    ).run_profile(profile["id"])
    assert outcome["run"]["status"] == "failed"
    assert "invalid worker output" in outcome["run"]["error_summary"]

    database = JobSpyDB(str(tmp_path / "timeout.db"))
    profile = database.create_profile(_profile())
    outcome = JobSpyService(
        database, _Collector(error=CollectionTimeout("worker timed out"))
    ).run_profile(profile["id"])
    assert outcome["run"]["status"] == "timeout"
    assert outcome["run"]["timed_out"] is True
    assert outcome["run"]["finished_at"] is not None


def test_service_rejects_overlapping_profile_run(tmp_path):
    from plugins.jobspy.service import JobSpyOverlapError, JobSpyService

    database = JobSpyDB(str(tmp_path / "overlap.db"))
    profile = database.create_profile(_profile())
    nested_error = []
    service = None

    def overlap():
        try:
            service.run_profile(profile["id"])
        except Exception as exc:
            nested_error.append(exc)

    service = JobSpyService(database, _Collector(before_return=overlap))
    service.run_profile(profile["id"])
    assert len(nested_error) == 1
    assert isinstance(nested_error[0], JobSpyOverlapError)


class _SDK:
    def __init__(self):
        self.created = []
        self.cancelled = []

    def create_schedule(self, **kwargs):
        self.created.append(kwargs)
        return {"id": f"schedule-{len(self.created)}"}

    def cancel_schedule(self, schedule_id):
        self.cancelled.append(schedule_id)
        return True


def test_profile_schedule_create_update_disable_delete_and_run_now(tmp_path):
    from plugins.jobspy.service import ProfileManager

    database = JobSpyDB(str(tmp_path / "profiles.db"))
    sdk = _SDK()
    runner = MagicMock()
    runner.run_profile.return_value = {"run": {"status": "success"}, "jobs": []}
    manager = ProfileManager(database, sdk, runner)

    created = manager.create_profile(_profile())
    assert created["schedule_id"] == "schedule-1"
    assert sdk.created[0]["trigger_config"] == {"minutes": 180}
    assert sdk.created[0]["action_type"] == "emit_event"

    updated = manager.update_profile(created["id"], {"cadence_minutes": 360})
    assert updated["schedule_id"] == "schedule-2"
    assert sdk.cancelled == ["schedule-1"]

    disabled = manager.update_profile(created["id"], {"enabled": False})
    assert disabled["schedule_id"] is None
    assert sdk.cancelled[-1] == "schedule-2"

    enabled = manager.update_profile(created["id"], {"enabled": True})
    assert enabled["schedule_id"] == "schedule-3"
    assert manager.run_now(created["id"])["run"]["status"] == "success"
    runner.run_profile.assert_called_once_with(created["id"], sdk=sdk)

    assert manager.delete_profile(created["id"]) is True
    assert sdk.cancelled[-1] == "schedule-3"
    assert database.get_profile(created["id"]) is None


def test_schedule_handler_ignores_unrelated_events_and_runs_owned_profile(tmp_path, monkeypatch):
    from plugins.jobspy import handler

    database = JobSpyDB(str(tmp_path / "handler.db"))
    profile = database.create_profile({**_profile(), "schedule_id": "owned-schedule"})
    runner = MagicMock()
    monkeypatch.setattr(handler, "jobspy_db", database)
    monkeypatch.setattr(handler, "JobSpyService", MagicMock(return_value=runner))
    sdk = MagicMock()

    unrelated = [
        {"schedule_id": "owned-schedule", "owner_type": "agent", "owner_id": "jobspy"},
        {"schedule_id": "owned-schedule", "owner_type": "plugin", "owner_id": "other"},
        {"schedule_id": "unknown", "owner_type": "plugin", "owner_id": "jobspy"},
    ]
    for event in unrelated:
        handler.on_schedule_fired(event, sdk)
    runner.run_profile.assert_not_called()

    handler.on_schedule_fired({
        "schedule_id": "owned-schedule",
        "owner_type": "plugin",
        "owner_id": "jobspy",
    }, sdk)
    runner.run_profile.assert_called_once_with(profile["id"], sdk=sdk)