"""Dashboard repository and blueprint tests for the JobSpy plugin."""

from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask

from plugins.jobspy.db import JobSpyDB


def _profile(**overrides):
    value = {
        "name": "Flutter",
        "options": {
            "sites": ["linkedin"],
            "search_term": "Flutter developer",
            "results_wanted": 10,
            "is_remote": True,
            "job_type": "contract",
        },
        "cadence_minutes": 180,
        "alert_threshold": 70,
        "enabled": True,
    }
    value.update(overrides)
    return value


def _job(url, title="Flutter Developer", site="linkedin"):
    return {
        "site": site,
        "job_url": url,
        "title": title,
        "company": "Example",
        "location": "Remote",
        "description": "Flutter Dart",
        "job_type": "contract",
        "is_remote": True,
    }


def _seed(database):
    profile = database.create_profile(_profile())
    run = database.create_run(profile["id"], "2026-07-10T10:00:00+00:00")
    high, _ = database.upsert_job(
        _job("https://example.com/jobs/high"),
        "2026-07-10T10:00:01+00:00",
    )
    low, _ = database.upsert_job(
        _job("https://example.com/jobs/low", "Android Intern", "indeed"),
        "2026-07-10T10:00:02+00:00",
    )
    database.save_match(
        job_id=high["id"], run_id=run["id"], local_score=84,
        model_score=92, final_score=87, reasons=["Flutter title match"],
    )
    database.save_match(
        job_id=low["id"], run_id=run["id"], local_score=30,
        model_score=None, final_score=30, reasons=["Low overlap"],
    )
    database.finish_run(
        run["id"], status="partial", site_counts={"linkedin": 1, "indeed": 1},
        error_summary="indeed: 429", finished_at="2026-07-10T10:01:00+00:00",
    )
    return profile, high, low


def test_job_listing_filters_review_status_and_summary(tmp_path):
    database = JobSpyDB(str(tmp_path / "dashboard.db"))
    profile, high, low = _seed(database)

    ranked = database.list_jobs(profile_id=profile["id"], min_score=70)
    assert [job["id"] for job in ranked] == [high["id"]]
    assert ranked[0]["final_score"] == 87
    assert ranked[0]["reasons"] == ["Flutter title match"]

    assert database.list_jobs(site="indeed")[0]["id"] == low["id"]
    assert database.list_jobs(search="Example")[0]["company"] == "Example"
    updated = database.update_review_status(high["id"], "saved")
    assert updated["review_status"] == "saved"
    assert database.list_jobs(review_status="saved")[0]["id"] == high["id"]

    summary = database.summary(high_score=70)
    assert summary["profiles"] == 1
    assert summary["enabled_profiles"] == 1
    assert summary["jobs"] == 2
    assert summary["new_high_matches"] == 0
    assert summary["partial_failures"] == 1
    assert summary["last_run"]["status"] == "partial"


class _SDK:
    config = {"SUBPROCESS_TIMEOUT_SECONDS": 30}

    def __init__(self):
        self.created = []
        self.cancelled = []

    def create_schedule(self, **kwargs):
        self.created.append(kwargs)
        return {"id": f"schedule-{len(self.created)}", "next_run_at": "2026-07-11"}

    def cancel_schedule(self, schedule_id):
        self.cancelled.append(schedule_id)
        return True

    def list_schedules(self):
        return [{"id": "schedule-1", "next_run_at": "2026-07-11T10:00:00+00:00"}]


class _LLM:
    model = "test-model"
    base_url = "https://llm.example.test"

    def __init__(self, result=None, content="Dear Hiring Manager,\n\nTailored letter"):
        self.result = result or {"success": True}
        self.content = content
        self.calls = []

    def chat_completion(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.result

    def extract_content(self, response):
        return self.content


def _app(monkeypatch, tmp_path):
    from plugins.jobspy import routes

    database = JobSpyDB(str(tmp_path / "routes.db"))
    sdk = _SDK()
    service = MagicMock()
    service.run_profile.return_value = {
        "run": {"id": 1, "status": "success"}, "jobs": [], "matches": []
    }
    monkeypatch.setattr(routes, "jobspy_db", database)
    monkeypatch.setattr(routes, "_get_sdk", lambda: sdk)
    monkeypatch.setattr(routes, "_get_service", lambda current_sdk: service)
    root = Path(__file__).parents[1]
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="test")
    app.register_blueprint(routes.create_blueprint())
    return app, database, sdk, service


def test_profile_routes_create_update_run_disable_delete(monkeypatch, tmp_path):
    app, database, sdk, service = _app(monkeypatch, tmp_path)
    client = app.test_client()

    created_response = client.post("/api/jobspy/profiles", json=_profile())
    assert created_response.status_code == 201
    created = created_response.get_json()["profile"]
    assert created["schedule_id"] == "schedule-1"

    listed = client.get("/api/jobspy/profiles").get_json()["profiles"]
    assert [profile["id"] for profile in listed] == [created["id"]]

    updated_response = client.put(
        f"/api/jobspy/profiles/{created['id']}",
        json={"cadence_minutes": 360},
    )
    assert updated_response.status_code == 200
    assert updated_response.get_json()["profile"]["schedule_id"] == "schedule-2"
    assert sdk.cancelled == ["schedule-1"]

    run_response = client.post(f"/api/jobspy/profiles/{created['id']}/run")
    assert run_response.status_code == 200
    service.run_profile.assert_called_once_with(created["id"], sdk=sdk)

    disabled = client.put(
        f"/api/jobspy/profiles/{created['id']}", json={"enabled": False}
    ).get_json()["profile"]
    assert disabled["schedule_id"] is None

    deleted = client.delete(f"/api/jobspy/profiles/{created['id']}")
    assert deleted.status_code == 200
    assert database.get_profile(created["id"]) is None


def test_profile_routes_create_and_update_min_score(monkeypatch, tmp_path):
    app, _, _, _ = _app(monkeypatch, tmp_path)
    client = app.test_client()
    values = _profile()
    values.pop("alert_threshold")
    values["min_score"] = 64

    created_response = client.post("/api/jobspy/profiles", json=values)
    assert created_response.status_code == 201
    created = created_response.get_json()["profile"]
    assert created["min_score"] == 64

    updated_response = client.put(
        f"/api/jobspy/profiles/{created['id']}", json={"min_score": 81}
    )
    assert updated_response.status_code == 200
    assert updated_response.get_json()["profile"]["min_score"] == 81

    legacy_response = client.put(
        f"/api/jobspy/profiles/{created['id']}", json={"alert_threshold": 72}
    )
    assert legacy_response.status_code == 200
    assert legacy_response.get_json()["profile"]["min_score"] == 72

    invalid_response = client.put(
        f"/api/jobspy/profiles/{created['id']}", json={"min_score": 101}
    )
    assert invalid_response.status_code == 400
    assert "min_score must be between 0 and 100" in invalid_response.get_json()["error"]


def test_profile_routes_validation_and_missing_records(monkeypatch, tmp_path):
    app, _, _, _ = _app(monkeypatch, tmp_path)
    client = app.test_client()
    invalid = _profile(options={"sites": ["google"], "search_term": "Flutter"})
    response = client.post("/api/jobspy/profiles", json=invalid)
    assert response.status_code == 400
    assert "Google search term" in response.get_json()["error"]

    assert client.get("/api/jobspy/profiles/missing").status_code == 404
    assert client.put("/api/jobspy/profiles/missing", json={"enabled": False}).status_code == 404
    assert client.delete("/api/jobspy/profiles/missing").status_code == 404
    assert client.post("/api/jobspy/profiles/missing/run").status_code == 404
    assert client.patch("/api/jobspy/jobs/missing/status", json={"status": "saved"}).status_code == 404


def test_jobs_runs_summary_page_and_status_routes(monkeypatch, tmp_path):
    app, database, _, _ = _app(monkeypatch, tmp_path)
    profile, high, _ = _seed(database)
    client = app.test_client()

    page = client.get("/jobspy")
    assert page.status_code == 200
    assert b"JobSpy" in page.data

    jobs = client.get(
        f"/api/jobspy/jobs?profile_id={profile['id']}&min_score=70&status=new"
    ).get_json()["jobs"]
    assert [job["id"] for job in jobs] == [high["id"]]

    saved = client.patch(
        f"/api/jobspy/jobs/{high['id']}/status", json={"status": "saved"}
    )
    assert saved.status_code == 200
    assert saved.get_json()["job"]["review_status"] == "saved"
    invalid = client.patch(
        f"/api/jobspy/jobs/{high['id']}/status", json={"status": "invalid"}
    )
    assert invalid.status_code == 400

    runs = client.get(
        f"/api/jobspy/runs?profile_id={profile['id']}"
    ).get_json()["runs"]
    assert runs[0]["status"] == "partial"
    summary = client.get("/api/jobspy/summary").get_json()
    assert summary["jobs"] == 2
    assert summary["next_run_at"] == "2026-07-11T10:00:00+00:00"


def test_clear_jobs_route_removes_jobs_and_matches_only(monkeypatch, tmp_path):
    app, database, _, _ = _app(monkeypatch, tmp_path)
    profile, high, low = _seed(database)
    client = app.test_client()

    response = client.delete("/api/jobspy/jobs")

    assert response.status_code == 200
    assert response.get_json() == {"cleared_jobs": 2, "success": True}
    assert database.get_job(high["id"]) is None
    assert database.get_job(low["id"]) is None
    assert database.get_latest_match(high["id"]) is None
    assert database.get_profile(profile["id"]) is not None
    assert len(database.list_runs(profile_id=profile["id"])) == 1


def test_cover_letter_route_uses_profile_and_job_without_persisting_result(
    monkeypatch, tmp_path
):
    app, database, sdk, _ = _app(monkeypatch, tmp_path)
    _, high, _ = _seed(database)
    sdk.config = {
        "SUBPROCESS_TIMEOUT_SECONDS": 30,
        "PROFILE_TEXT": "Flutter engineer with fintech and payments experience",
    }
    llm = _LLM()
    monkeypatch.setattr("backend.llm_client.get_llm_client", lambda: llm)

    response = app.test_client().post(
        f"/api/jobspy/jobs/{high['id']}/cover-letter"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "cover_letter": "Dear Hiring Manager,\n\nTailored letter"
    }
    messages, kwargs = llm.calls[0]
    assert "untrusted" in messages[0]["content"]
    assert "Flutter engineer with fintech" in messages[1]["content"]
    assert "Flutter Developer" in messages[1]["content"]
    assert "Flutter Dart" in messages[1]["content"]
    assert kwargs["log_file"] is False
    assert "cover_letter" not in database.get_job(high["id"])


def test_cover_letter_route_reports_missing_inputs_and_model_failure(
    monkeypatch, tmp_path
):
    app, database, sdk, _ = _app(monkeypatch, tmp_path)
    _, high, _ = _seed(database)
    client = app.test_client()

    assert client.post(
        "/api/jobspy/jobs/missing/cover-letter"
    ).status_code == 404

    missing_profile = client.post(
        f"/api/jobspy/jobs/{high['id']}/cover-letter"
    )
    assert missing_profile.status_code == 400
    assert "profile text" in missing_profile.get_json()["error"].lower()

    sdk.config = {
        "SUBPROCESS_TIMEOUT_SECONDS": 30,
        "PROFILE_TEXT": "Flutter engineer",
    }
    no_description, _ = database.upsert_job(
        _job("https://example.com/jobs/no-description") | {"description": ""}
    )
    missing_description = client.post(
        f"/api/jobspy/jobs/{no_description['id']}/cover-letter"
    )
    assert missing_description.status_code == 400
    assert "description" in missing_description.get_json()["error"].lower()

    failed_llm = _LLM(result={"success": False, "error_type": "api_error"})
    monkeypatch.setattr("backend.llm_client.get_llm_client", lambda: failed_llm)
    failed = client.post(f"/api/jobspy/jobs/{high['id']}/cover-letter")
    assert failed.status_code == 502
    assert "model" in failed.get_json()["error"].lower()


def test_profile_form_only_submits_google_query_for_google_searches(
    monkeypatch, tmp_path
):
    app, _, _, _ = _app(monkeypatch, tmp_path)
    page = app.test_client().get("/jobspy")
    html = page.get_data(as_text=True)

    assert 'id="p-google"' in html
    assert 'id="p-google" disabled' in html
    assert "function syncGoogleSearchField()" in html
    assert "google_search_term:googleSite.checked?" in html
    assert 'id="p-min-score"' in html
    assert "min_score:+document.getElementById('p-min-score').value" in html
    assert 'id="clear-jobs"' in html
    assert "confirm('Clear all collected jobs?')" in html
    assert "api('/api/jobspy/jobs',{method:'DELETE'})" in html
    assert "Generate cover letter" in html
    assert "generateCoverLetter(" in html
    assert "copyCoverLetter()" in html


def test_manifest_and_dashboard_card_are_registered(tmp_path):
    import json
    from plugins.jobspy import handler

    root = Path(__file__).parents[1]
    manifest = json.loads(
        (root / "plugins" / "jobspy" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["nav_items"] == [{"label": "JobSpy", "path": "/jobspy"}]
    assert manifest["dashboard_cards"][0]["handler"] == "dashboard_jobspy_card"
    paths = {route["path"] for route in manifest["routes"]}
    assert "/jobspy" in paths
    assert "/api/jobspy/profiles" in paths
    assert "/api/jobspy/jobs" in paths
    assert "/api/jobspy/jobs/<job_id>/cover-letter" in paths
    jobs_route = next(
        route for route in manifest["routes"]
        if route["path"] == "/api/jobspy/jobs"
    )
    assert jobs_route["methods"] == ["GET", "DELETE"]

    database = JobSpyDB(str(tmp_path / "card.db"))
    _seed(database)
    original = handler.jobspy_db
    handler.jobspy_db = database
    try:
        card = handler.dashboard_jobspy_card(MagicMock(config={}))
    finally:
        handler.jobspy_db = original
    assert card["id"] == "jobspy_matches"
    assert card["link"] == "/jobspy"