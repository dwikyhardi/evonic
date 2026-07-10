"""Foundation tests for the JobSpy plugin."""

import json
from pathlib import Path

from backend.plugin_lifecycle import PluginManager


def _job(*, url="https://example.com/jobs/42?utm_source=test"):
    return {
        "site": "linkedin",
        "job_url": url,
        "title": "Senior Flutter Developer",
        "company": "Example Co",
        "location": "Remote",
        "description": "Build payment applications with Flutter and Dart.",
        "job_type": "contract",
        "is_remote": True,
    }


def test_schema_initialization_is_idempotent(tmp_path):
    from plugins.jobspy.db import JobSpyDB

    db_path = tmp_path / "jobspy.db"
    JobSpyDB(str(db_path))
    database = JobSpyDB(str(db_path))

    assert database.schema_version() == 1
    assert set(database.table_names()) >= {
        "search_profiles",
        "scrape_runs",
        "jobs",
        "job_matches",
    }


def test_profile_repository_round_trip(tmp_path):
    from plugins.jobspy.db import JobSpyDB

    database = JobSpyDB(str(tmp_path / "jobspy.db"))
    created = database.create_profile({
        "name": "Flutter contracts",
        "options": {
            "sites": ["linkedin", "indeed"],
            "search_term": "Flutter developer",
            "location": "Indonesia",
        },
        "cadence_minutes": 180,
        "enabled": True,
        "alert_threshold": 78,
    })

    assert created["name"] == "Flutter contracts"
    assert created["options"]["sites"] == ["linkedin", "indeed"]
    assert created["enabled"] is True

    updated = database.update_profile(created["id"], {
        "schedule_id": "schedule-123",
        "enabled": False,
        "alert_threshold": 85,
    })
    assert updated["schedule_id"] == "schedule-123"
    assert updated["enabled"] is False
    assert updated["alert_threshold"] == 85
    assert database.list_profiles()[0]["id"] == created["id"]

    assert database.delete_profile(created["id"]) is True
    assert database.get_profile(created["id"]) is None


def test_job_identity_and_upsert_are_deterministic(tmp_path):
    from plugins.jobspy.db import JobSpyDB, canonical_job_identity, canonical_job_url

    database = JobSpyDB(str(tmp_path / "jobspy.db"))
    first_identity = canonical_job_identity(_job())
    tracking_variant = canonical_job_identity(
        _job(url="https://EXAMPLE.com/jobs/42/?utm_medium=email#details")
    )
    assert first_identity == tracking_variant

    first, created = database.upsert_job(_job(), seen_at="2026-01-01T00:00:00+00:00")
    second, created_again = database.upsert_job(
        {**_job(), "description": "Updated description"},
        seen_at="2026-01-02T00:00:00+00:00",
    )

    assert created is True
    assert created_again is False
    assert second["id"] == first["id"]
    assert second["first_seen_at"] == "2026-01-01T00:00:00+00:00"
    assert second["last_seen_at"] == "2026-01-02T00:00:00+00:00"
    assert second["description"] == "Updated description"

    fallback = canonical_job_identity({
        "site": "indeed",
        "title": " Flutter Developer ",
        "company": "Example Co",
        "location": "Jakarta",
    })
    assert fallback == canonical_job_identity({
        "site": "INDEED",
        "title": "flutter   developer",
        "company": "example co",
        "location": " jakarta ",
    })
    assert canonical_job_url("javascript:alert(1)") == ""
    assert canonical_job_url("//example.com/jobs/42") == ""


def test_runs_matches_and_alert_state_round_trip(tmp_path):
    from plugins.jobspy.db import JobSpyDB

    database = JobSpyDB(str(tmp_path / "jobspy.db"))
    profile = database.create_profile({
        "name": "Mobile",
        "options": {"sites": ["google"], "search_term": "mobile developer"},
    })
    run = database.create_run(profile["id"], started_at="2026-01-01T00:00:00+00:00")
    job, _ = database.upsert_job(_job())

    match = database.save_match(
        job_id=job["id"],
        run_id=run["id"],
        local_score=74,
        model_score=88,
        final_score=81,
        reasons=["Flutter title match", "Remote contract"],
    )
    assert match["reasons"] == ["Flutter title match", "Remote contract"]

    completed = database.finish_run(
        run["id"],
        status="partial",
        site_counts={"linkedin": 1, "indeed": 0},
        error_summary="Indeed returned 429",
        timed_out=False,
        finished_at="2026-01-01T00:01:00+00:00",
    )
    assert completed["site_counts"] == {"linkedin": 1, "indeed": 0}
    assert completed["status"] == "partial"

    database.record_alert_result(job["id"], success=False, error="channel unavailable")
    failed = database.get_job(job["id"])
    assert failed["alerted_at"] is None
    assert failed["alert_attempts"] == 1
    assert failed["alert_error"] == "channel unavailable"

    database.record_alert_result(
        job["id"], success=True, alerted_at="2026-01-01T00:02:00+00:00"
    )
    alerted = database.get_job(job["id"])
    assert alerted["alerted_at"] == "2026-01-01T00:02:00+00:00"
    assert alerted["alert_attempts"] == 2
    assert alerted["alert_error"] is None


def test_manifest_is_discoverable_and_config_defaults_are_typed():
    plugin_dir = Path(__file__).parents[1] / "plugins" / "jobspy"
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "jobspy"
    assert "schedule_fired" in manifest["events"]

    manager = PluginManager.__new__(PluginManager)
    config = manager.get_plugin_config("jobspy")
    assert isinstance(config["RERANK_ENABLED"], bool)
    assert isinstance(config["LOCAL_SCORE_THRESHOLD"], int)
    assert isinstance(config["RERANK_TOP_N"], int)
    assert isinstance(config["SUBPROCESS_TIMEOUT_SECONDS"], int)
    assert config["PROFILE_TEXT"] == ""