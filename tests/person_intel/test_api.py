import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import web.app as web_app


def _login(client: TestClient) -> None:
    response = client.post("/api/login", json={"password": "9876"})
    assert response.status_code == 200
    client.cookies.set("session_id", response.json()["session_id"])


def test_person_profile_job_status_model_instantiates() -> None:
    status = web_app.PersonProfileJobStatus(job_id="job-123", status="pending")

    assert status.job_id == "job-123"
    assert status.status == "pending"


def test_person_profile_job_lifecycle(monkeypatch) -> None:
    from agent.pipeline.state.schemas import (
        PersonClaim,
        PersonClaimEvidence,
        PersonProfileOutput,
        PersonProfileSections,
        PersonSubject,
    )

    async def fake_build_profile(self, req):
        profile = PersonProfileOutput(
            subject=PersonSubject(
                primary_profile_url=req.primary_profile_url,
                normalized_profile_url=req.primary_profile_url,
            ),
            sections=PersonProfileSections(
                interests_lifestyle="One. Two.",
                strengths=[f"✅ Strength {i}" for i in range(1, 6)],
                more_details="Details.",
                biggest_achievements=["A", "B", "C"],
                values_beliefs="One. Two.",
                key_points=["K1", "K2", "K3", "K4", "K5"],
                coolest_fact="Fact.",
                top_risk="Main uncertainty is limited evidence.",
            ),
            claims=[
                PersonClaim(
                    claim_id="claim_1",
                    text="Fact",
                    section="key_points",
                    evidence=[
                        PersonClaimEvidence(
                            url=req.primary_profile_url,
                            snippet_or_field="field: value",
                            source_type="apify_profile",
                            retrieved_at="2026-03-04T00:00:00Z",
                        )
                    ],
                    confidence=0.8,
                    timestamp="2026-03-04T00:00:00Z",
                    status="supported",
                )
            ],
            unknowns=[],
            provenance_index=[],
        )
        return profile, "## INTERESTS & LIFESTYLE\nOne. Two.\n", "abc"

    monkeypatch.setattr(
        web_app,
        "_person_service",
        type("S", (), {"build_profile": fake_build_profile})(),
    )

    with TestClient(web_app.app) as client:
        _login(client)

        created = client.post(
            "/api/person-profile/jobs",
            json={"primary_profile_url": "https://www.linkedin.com/in/example"},
        )
        assert created.status_code == 200
        job_id = created.json()["job_id"]

        for _ in range(20):
            status = client.get(f"/api/person-profile/status/{job_id}")
            assert status.status_code == 200
            payload = status.json()
            if payload["status"] == "done":
                assert payload["result"]["profile_json"]["claims"]
                return
            time.sleep(0.05)

        raise AssertionError("Person job did not complete in time")


def test_person_profile_job_resumes_from_persisted_state(monkeypatch) -> None:
    from agent.pipeline.state.schemas import (
        PersonClaim,
        PersonClaimEvidence,
        PersonProfileOutput,
        PersonProfileSections,
        PersonSubject,
    )

    async def fake_build_profile(self, req):
        profile = PersonProfileOutput(
            subject=PersonSubject(
                primary_profile_url=req.primary_profile_url,
                normalized_profile_url=req.primary_profile_url,
            ),
            sections=PersonProfileSections(
                interests_lifestyle="One. Two.",
                strengths=[f"✅ Strength {i}" for i in range(1, 6)],
                more_details="Details.",
                biggest_achievements=["A", "B", "C"],
                values_beliefs="One. Two.",
                key_points=["K1", "K2", "K3", "K4", "K5"],
                coolest_fact="Fact.",
                top_risk="Main uncertainty is limited evidence.",
            ),
            claims=[
                PersonClaim(
                    claim_id="claim_1",
                    text="Fact",
                    section="key_points",
                    evidence=[
                        PersonClaimEvidence(
                            url=req.primary_profile_url,
                            snippet_or_field="field: value",
                            source_type="apify_profile",
                            retrieved_at="2026-03-04T00:00:00Z",
                        )
                    ],
                    confidence=0.8,
                    timestamp="2026-03-04T00:00:00Z",
                    status="supported",
                )
            ],
            unknowns=[],
            provenance_index=[],
        )
        return profile, "## INTERESTS & LIFESTYLE\nOne. Two.\n", "abc"

    class FakeDb:
        def __init__(self) -> None:
            self.upserts: list[dict[str, object]] = []

        @staticmethod
        def is_configured() -> bool:
            return True

        @staticmethod
        def load_person_profile_job(job_id):
            if job_id != "resume-123":
                return None
            return {
                "person_job_id": job_id,
                "status": "running",
                "progress": "Collecting evidence...",
                "request_payload": {
                    "primary_profile_url": "https://www.linkedin.com/in/example",
                    "company_slug": "apaleo",
                    "person_key": "apaleo:founder:3",
                },
                "result_payload": None,
                "error": None,
            }

        def upsert_person_profile_job(self, job_id, **kwargs):
            self.upserts.append({"job_id": job_id, **kwargs})

        @staticmethod
        def prune_person_profile_jobs(company_slug, person_key, keep_person_job_id):
            return True

    fake_db = FakeDb()
    monkeypatch.setattr(
        web_app,
        "_person_service",
        type("S", (), {"build_profile": fake_build_profile})(),
    )
    monkeypatch.setattr(web_app, "db", fake_db)
    web_app._person_jobs.clear()
    web_app._person_job_tasks.clear()

    with TestClient(web_app.app) as client:
        _login(client)

        for _ in range(20):
            status = client.get("/api/person-profile/status/resume-123")
            assert status.status_code == 200
            payload = status.json()
            if payload["status"] == "done":
                assert payload["result"]["profile_json"]["claims"]
                assert any(item["progress"] == "Resuming after restart..." for item in fake_db.upserts)
                return
            time.sleep(0.05)

        raise AssertionError("Persisted person job did not resume in time")


def test_latest_person_profile_loads_from_db(monkeypatch) -> None:
    class FakeDb:
        @staticmethod
        def is_configured() -> bool:
            return True

        @staticmethod
        def load_latest_person_profile_job(company_slug, person_key):
            return {
                "person_job_id": "job-latest",
                "company_slug": company_slug,
                "person_key": person_key,
                "status": "done",
                "progress": "Profile completed",
                "request_payload": {
                    "company_slug": company_slug,
                    "person_key": person_key,
                },
                "result_payload": {
                    "profile_json": {
                        "subject": {
                            "full_name": "Ulrich Pillau",
                            "normalized_profile_url": "https://www.linkedin.com/in/ulrich-pillau",
                        }
                    }
                },
                "error": None,
                "created_at": "2026-03-17T00:00:00Z",
                "updated_at": "2026-03-17T00:05:00Z",
            }

    monkeypatch.setattr(web_app, "db", FakeDb())

    with TestClient(web_app.app) as client:
        _login(client)
        response = client.get(
            "/api/person-profile/latest",
            params={"company_slug": "apaleo", "person_key": "apaleo:founder:1"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-latest"
    assert payload["status"] == "done"
    assert payload["result"]["profile_json"]["subject"]["full_name"] == "Ulrich Pillau"


def test_persist_person_job_prunes_older_profiles_when_terminal(monkeypatch) -> None:
    calls = {"upsert": [], "prune": []}

    class FakeDb:
        @staticmethod
        def is_configured() -> bool:
            return True

        @staticmethod
        def upsert_person_profile_job(*args, **kwargs):
            calls["upsert"].append((args, kwargs))

        @staticmethod
        def prune_person_profile_jobs(company_slug, person_key, keep_person_job_id):
            calls["prune"].append({
                "company_slug": company_slug,
                "person_key": person_key,
                "keep_person_job_id": keep_person_job_id,
            })
            return True

    monkeypatch.setattr(web_app, "db", FakeDb())

    job_id = "job-prune"
    web_app._person_jobs[job_id] = web_app.PersonProfileJobStatus(
        job_id=job_id,
        status="done",
        progress="Profile completed",
        result={"profile_json": {"subject": {"full_name": "Ulrich Pillau"}}},
    )

    try:
        web_app._persist_person_job(job_id, {
            "company_slug": "apaleo",
            "person_key": "apaleo:founder:1",
        })
    finally:
        web_app._person_jobs.pop(job_id, None)

    assert calls["upsert"]
    assert calls["prune"] == [{
        "company_slug": "apaleo",
        "person_key": "apaleo:founder:1",
        "keep_person_job_id": "job-prune",
    }]
