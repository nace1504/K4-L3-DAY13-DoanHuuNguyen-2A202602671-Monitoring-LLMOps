from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_dashboard as dash  # noqa: E402
from app.metrics import percentile  # noqa: E402


def _write_logs(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "logs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _fake_rows() -> list[dict]:
    rows = []
    for i, latency in enumerate([100, 200, 300, 4000]):
        ts = f"2026-09-30T04:0{i}:00Z"
        rows.append({"event": "request_received", "ts": ts, "service": "api"})
        rows.append({
            "event": "response_sent", "ts": ts, "service": "api", "latency_ms": latency, "ttft_ms": 50,
            "cost_usd": 0.25, "tokens_in": 10, "tokens_out": 100, "quality_score": 0.5 + i * 0.1,
            "tool_name": "retrieval", "tool_success": True,
        })
    rows.append({"event": "request_received", "ts": "2026-09-30T04:04:00Z", "service": "api"})
    rows.append({
        "event": "request_failed", "ts": "2026-09-30T04:04:00Z", "service": "api",
        "error_type": "RuntimeError", "tool_name": "retrieval", "tool_success": False,
    })
    rows.append({"event": "app_started", "ts": "2026-09-30T04:04:30Z", "tool_success": None})
    return rows


def test_summary_aggregates_match_expected_values(tmp_path: Path) -> None:
    records = dash.load_records(_write_logs(tmp_path, _fake_rows()))
    summary = dash.summarize(records, minutes=60)

    assert summary["requests"] == 5
    assert summary["error_rate_pct"] == 20.0
    assert summary["error_breakdown"] == {"RuntimeError": 1}
    assert summary["retrieval_success_pct"] == 80.0  # 4 true / 5 non-null
    assert summary["cost_total"] == 1.0
    assert summary["tokens_in"] == 40 and summary["tokens_out"] == 400
    assert summary["quality_mean"] == 0.65
    assert summary["p95"] == percentile([100, 200, 300, 4000], 95) == 4000.0
    assert summary["p50"] == percentile([100, 200, 300, 4000], 50)


def test_filter_window_keeps_only_last_minutes(tmp_path: Path) -> None:
    rows = _fake_rows() + [{"event": "request_received", "ts": "2026-09-30T02:00:00Z"}]
    records = dash.load_records(_write_logs(tmp_path, rows))

    window, start, end = dash.filter_window(records, minutes=60)

    assert end == datetime(2026, 9, 30, 4, 4, 30, tzinfo=timezone.utc)
    assert all(r["_ts"] > start for r in window)
    assert len(window) == len(records) - 1


def test_empty_inputs_do_not_divide_by_zero() -> None:
    assert dash.error_rate_pct([]) == 0.0
    assert dash.retrieval_success_pct([]) is None
    assert dash.passes(None, "lte", 1) is None


def test_threshold_operators_follow_config(tmp_path: Path) -> None:
    cfg = dash.load_config(REPO_ROOT / "config" / "dashboard.yaml")
    latency = cfg["panels_by_id"]["latency"]["threshold"]
    quality = cfg["panels_by_id"]["quality"]["threshold"]

    assert dash.passes(latency["value"], latency["operator"], latency["value"]) is True
    assert dash.passes(latency["value"] + 1, latency["operator"], latency["value"]) is False
    assert dash.passes(quality["value"] - 0.01, quality["operator"], quality["value"]) is False


def test_start_end_range_accepts_utc_and_vietnam_time(tmp_path: Path) -> None:
    records = dash.load_records(_write_logs(tmp_path, _fake_rows()))
    start = dash.parse_cli_time("2026-09-30T11:01:00+07:00")  # = 04:01Z
    end = dash.parse_cli_time("2026-09-30T04:03:00Z")

    window = dash.filter_range(records, start, end)

    assert start == datetime(2026, 9, 30, 4, 1, tzinfo=timezone.utc)
    assert {r["ts"] for r in window} == {
        "2026-09-30T04:01:00Z", "2026-09-30T04:02:00Z", "2026-09-30T04:03:00Z",
    }
    summary = dash.summarize(window, minutes=(end - start).total_seconds() / 60)
    assert summary["requests"] == 3
    assert summary["rate_per_minute"] == 1.5


def test_short_windows_use_10s_buckets_including_first_partial_bucket() -> None:
    start = datetime(2026, 9, 30, 4, 33, 49, tzinfo=timezone.utc)
    end = datetime(2026, 9, 30, 4, 35, 50, tzinfo=timezone.utc)

    secs = dash.bucket_seconds_for(start, end)
    buckets = dash.time_buckets(start, end, secs)

    assert secs == 10
    assert dash.bucket_seconds_for(start, start.replace(hour=5, minute=34)) == 60
    assert buckets[0] == datetime(2026, 9, 30, 4, 33, 40, tzinfo=timezone.utc)
    assert buckets[-1] == datetime(2026, 9, 30, 4, 35, 50, tzinfo=timezone.utc)
