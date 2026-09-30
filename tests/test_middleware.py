from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app

CHAT_BODY = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Explain observability",
}


def _post_chats(headers_list: list[dict[str, str]]) -> list[httpx.Response]:
    async def send() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [await client.post("/chat", json=CHAT_BODY, headers=h) for h in headers_list]

    return asyncio.run(send())


def _read_events(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_generates_request_id_when_header_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    (response,) = _post_chats([{}])

    assert response.status_code == 200
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
    assert response.headers["x-response-time-ms"].isdigit()
    assert response.json()["correlation_id"] == response.headers["x-request-id"]


def test_propagates_incoming_request_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    (response,) = _post_chats([{"x-request-id": "req-abcdef12"}])

    assert response.headers["x-request-id"] == "req-abcdef12"


def test_consecutive_requests_do_not_share_correlation_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    first, second = _post_chats([{}, {}])

    events = [e for e in _read_events(log_path) if e["event"] == "request_received"]
    logged_ids = [e["correlation_id"] for e in events]
    assert len(logged_ids) == 2
    assert logged_ids[0] != logged_ids[1]
    assert logged_ids == [first.headers["x-request-id"], second.headers["x-request-id"]]


def test_request_received_log_is_enriched(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    _post_chats([{}])

    event = next(e for e in _read_events(log_path) if e["event"] == "request_received")
    for field in ("correlation_id", "user_id_hash", "session_id", "feature", "model", "env"):
        assert event.get(field), field
    assert event["session_id"] == "session-01"
    assert event["feature"] == "qa"
    assert "student-01" not in json.dumps(event)
