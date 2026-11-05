import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.errors import AlreadyRunningError
from app.http import create_app
from app.services.email_processor import CycleResult
from app.workers.gmail_poller import AgentRunner
from tests.fakes import FakeDeepSeek, FakeDrive, FakeGmail, gmail_message


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "test-password-12"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_health_is_public_and_api_requires_auth():
    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert client.get("/api/stats").status_code == 401
        assert client.get("/health/integrations").status_code == 401
        _login(client)
        assert client.get("/api/stats").status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "System health" in page.text
        assert "test-secret-key" not in page.text


def test_config_status_hides_secret_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-visible-ok")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "super-secret-client-secret-value")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "super-secret-refresh-token-value")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "super-secret-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    get_settings.cache_clear()
    settings = Settings()
    with TestClient(create_app(settings, overrides={"deepseek": FakeDeepSeek()})) as client:
        _login(client)
        response = client.get("/api/config/status")
        body = response.text
        assert response.status_code == 200
        assert "super-secret-client-secret-value" not in body
        assert "super-secret-refresh-token-value" not in body
        assert "super-secret-deepseek-key" not in body
        assert "deepseek-chat" in body
        configured = {item["name"]: item["configured"] for item in response.json()["flags"]}
        assert configured["GOOGLE_REFRESH_TOKEN"] is True
        assert configured["DEEPSEEK_API_KEY"] is True
    get_settings.cache_clear()


def test_manual_run_processes_a_message_and_blocks_a_second_runner():
    message = gmail_message(
        "msg-api",
        "Back Office",
        "Attached.",
        [("invoice.pdf", "application/pdf", "att-api", 16)],
    )
    gmail = FakeGmail({"msg-api": message}, {("msg-api", "att-api"): b"%PDF-1.4 api"})
    drive = FakeDrive()
    with TestClient(create_app(overrides={"gmail": gmail, "drive": drive})) as client:
        _login(client)
        response = client.post("/api/agent/run", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["uploaded"] == 1
        assert body["detail"] == "completed"
        logs = client.get("/api/logs?status=success")
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1
        attachments = client.get("/api/attachments")
        assert attachments.json()["items"][0]["google_drive_file_id"] == "drive-1"
        again = client.post("/api/agent/run", json={})
        assert again.json()["uploaded"] == 0
        assert len(drive.uploads) == 1


@pytest.mark.asyncio
async def test_runner_rejects_overlapping_cycles():
    class SlowProcessor:
        async def run_cycle(self, reprocess_failed: bool = False) -> CycleResult:
            del reprocess_failed
            await asyncio.sleep(0.2)
            return CycleResult(detail="completed")

    runner = AgentRunner(SlowProcessor())  # type: ignore[arg-type]
    first = asyncio.create_task(runner.run_once())
    await asyncio.sleep(0.05)
    with pytest.raises(AlreadyRunningError):
        await runner.run_once()
    await first


def test_login_rejects_a_wrong_password():
    with TestClient(create_app()) as client:
        response = client.post(
            "/login",
            data={"username": "admin", "password": "wrong-password-12"},
        )
        assert response.status_code == 401
        assert "not accepted" in response.text
        assert client.get("/api/emails").status_code == 401
