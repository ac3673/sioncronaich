"""Tests for the FastAPI web application."""

from pathlib import Path

from fastapi.testclient import TestClient

from sioncronaich.db import get_jobs

JOB_PAYLOAD = {
    "job_name": "test-job",
    "hostname": "test-host",
    "command": "echo hello",
    "stdout": "hello\n",
    "stderr": "",
    "exit_code": 0,
    "started_at": "2024-01-01T12:00:00+00:00",
    "finished_at": "2024-01-01T12:00:05+00:00",
}


class TestPostJob:
    def test_returns_201(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        assert response.status_code == 201

    def test_response_contains_id(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        assert "id" in response.json()

    def test_response_fields_match_payload(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        data = response.json()
        assert data["job_name"] == JOB_PAYLOAD["job_name"]
        assert data["hostname"] == JOB_PAYLOAD["hostname"]
        assert data["command"] == JOB_PAYLOAD["command"]
        assert data["exit_code"] == JOB_PAYLOAD["exit_code"]

    def test_response_contains_computed_fields(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        data = response.json()
        assert "duration_seconds" in data
        assert "succeeded" in data
        assert data["duration_seconds"] == 5.0
        assert data["succeeded"] is True

    def test_persists_to_database(self, client: TestClient, db_path: Path):
        client.post("/jobs", json=JOB_PAYLOAD)
        jobs = get_jobs(db_path=db_path)
        assert len(jobs) == 1

    def test_invalid_payload_returns_422(self, client: TestClient):
        response = client.post("/jobs", json={"job_name": "incomplete"})
        assert response.status_code == 422

    def test_failed_job(self, client: TestClient):
        payload = {**JOB_PAYLOAD, "exit_code": 1, "stderr": "error\n"}
        response = client.post("/jobs", json=payload)
        data = response.json()
        assert data["succeeded"] is False
        assert data["exit_code"] == 1


class TestListJobs:
    def test_empty_returns_empty_list(self, client: TestClient):
        response = client.get("/jobs")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_posted_jobs(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs")
        assert len(response.json()) == 1

    def test_newest_first_ordering(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "second-job"})
        results = client.get("/jobs").json()
        assert results[0]["job_name"] == "second-job"
        assert results[1]["job_name"] == "test-job"

    def test_limit_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs", params={"limit": 3})
        assert len(response.json()) == 3

    def test_offset_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        all_results = client.get("/jobs").json()
        offset_results = client.get("/jobs", params={"offset": 2}).json()
        assert offset_results[0]["id"] == all_results[2]["id"]


class TestDashboard:
    def test_returns_200(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200

    def test_returns_html(self, client: TestClient):
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_empty_state_message(self, client: TestClient):
        response = client.get("/")
        assert "No job results yet" in response.text

    def test_renders_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "test-job" in response.text

    def test_renders_hostname(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "test-host" in response.text

    def test_ok_badge_for_success(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "badge-ok" in response.text

    def test_err_badge_for_failure(self, client: TestClient):
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        response = client.get("/")
        assert "badge-err" in response.text
