"""Render the 6-panel runtime dashboard from data/logs.jsonl.

Panel titles, time range, refresh interval and thresholds all come from
config/dashboard.yaml; percentiles reuse app.metrics.percentile so the
dashboard matches the numbers the app itself reports.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

DEFAULT_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
DEFAULT_LOGS = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "submission" / "evidence" / "11-dashboard-overview.png"
VN_TZ = timezone(timedelta(hours=7))


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "ts" in rec and "event" in rec:
            rec["_ts"] = parse_ts(rec["ts"])
            records.append(rec)
    return records


def filter_window(
    records: list[dict], minutes: int, end: datetime | None = None
) -> tuple[list[dict], datetime, datetime]:
    """Keep records in (end - minutes, end]; end defaults to the newest record."""
    if end is None:
        end = max((r["_ts"] for r in records), default=datetime.now(timezone.utc))
    start = end - timedelta(minutes=minutes)
    return [r for r in records if start < r["_ts"] <= end], start, end


def events(records: list[dict], name: str) -> list[dict]:
    return [r for r in records if r.get("event") == name]


def error_rate_pct(records: list[dict]) -> float:
    received = len(events(records, "request_received"))
    failed = len(events(records, "request_failed"))
    return failed / received * 100 if received else 0.0


def error_breakdown(records: list[dict]) -> dict[str, int]:
    return dict(Counter(r.get("error_type") or "unknown" for r in events(records, "request_failed")))


def retrieval_success_pct(records: list[dict]) -> float | None:
    flags = [r["tool_success"] for r in records if r.get("tool_success") is not None]
    return sum(1 for f in flags if f is True) / len(flags) * 100 if flags else None


def summarize(records: list[dict], minutes: int) -> dict:
    responses = events(records, "response_sent")
    latencies = [r["latency_ms"] for r in responses if "latency_ms" in r]
    ttfts = [r["ttft_ms"] for r in responses if "ttft_ms" in r]
    quality = [r["quality_score"] for r in responses if "quality_score" in r]
    received = len(events(records, "request_received"))
    return {
        "requests": received,
        "responses": len(responses),
        "failed": len(events(records, "request_failed")),
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "ttft_p95": percentile(ttfts, 95),
        "rate_per_minute": received / minutes if minutes else 0.0,
        "error_rate_pct": error_rate_pct(records),
        "error_breakdown": error_breakdown(records),
        "retrieval_success_pct": retrieval_success_pct(records),
        "cost_total": round(sum(r.get("cost_usd", 0.0) for r in responses), 6),
        "tokens_in": sum(r.get("tokens_in", 0) for r in responses),
        "tokens_out": sum(r.get("tokens_out", 0) for r in responses),
        "quality_mean": round(mean(quality), 4) if quality else None,
    }


def minute_buckets(start: datetime, end: datetime) -> list[datetime]:
    first = (start + timedelta(minutes=1)).replace(second=0, microsecond=0)
    buckets, cur = [], first
    while cur <= end:
        buckets.append(cur)
        cur += timedelta(minutes=1)
    return buckets


def by_minute(records: list[dict]) -> dict[datetime, list[dict]]:
    grouped: dict[datetime, list[dict]] = {}
    for r in records:
        grouped.setdefault(r["_ts"].replace(second=0, microsecond=0), []).append(r)
    return grouped


def passes(value: float | None, operator: str, threshold: float) -> bool | None:
    if value is None:
        return None
    return value <= threshold if operator == "lte" else value >= threshold


def panel_values(summary: dict) -> dict[str, float | None]:
    """Value each panel's threshold aggregation is evaluated against."""
    return {
        "latency": summary["p95"],
        "traffic": summary["rate_per_minute"],
        "errors": summary["error_rate_pct"],
        "cost": summary["cost_total"],
        "tokens": max(summary["tokens_in"], summary["tokens_out"]),
        "quality": summary["quality_mean"],
    }


def load_config(path: Path) -> dict:
    dashboard = yaml.safe_load(path.read_text(encoding="utf-8"))["dashboard"]
    dashboard["panels_by_id"] = {p["id"]: p for p in dashboard["panels"]}
    return dashboard


def render(cfg: dict, records: list[dict], start: datetime, end: datetime, summary: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    panels = cfg["panels_by_id"]
    grouped = by_minute(records)
    buckets = minute_buckets(start, end)
    active = [b for b in buckets if b in grouped]

    fig, axes = plt.subplots(2, 3, figsize=(21, 11.5), dpi=100)
    fmt = lambda d: d.strftime("%Y-%m-%d %H:%M")  # noqa: E731
    fig.suptitle(
        f"{cfg['title']} — last {cfg['time_range_minutes']} min · refresh {cfg['refresh_seconds']}s\n"
        f"{fmt(start)} → {fmt(end)} UTC  |  {fmt(start.astimezone(VN_TZ))} → {fmt(end.astimezone(VN_TZ))} giờ Việt Nam (UTC+7)"
        f"  |  {summary['requests']} requests · source: data/logs.jsonl",
        fontsize=14, fontweight="bold",
    )

    def threshold_line(ax, panel_id: str, label_unit: str) -> None:
        th = panels[panel_id]["threshold"]
        sign = "≤" if th["operator"] == "lte" else "≥"
        ax.axhline(th["value"], color="#d62728", linestyle="--", linewidth=1.5,
                   label=f"threshold {th['aggregation']} {sign} {th['value']:,} {label_unit}")

    def status_text(ax, panel_id: str, text: str) -> None:
        th = panels[panel_id]["threshold"]
        ok = passes(panel_values(summary)[panel_id], th["operator"], th["value"])
        verdict = {True: "OK", False: "BREACH", None: "NO DATA"}[ok]
        color = {True: "#2ca02c", False: "#d62728", None: "#7f7f7f"}[ok]
        ax.text(0.01, 0.98, f"[{verdict}] {text}", transform=ax.transAxes, va="top", fontsize=10,
                color=color, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor=color))

    def minute_axis(ax) -> None:
        ax.set_xlim(start, end)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))
        ax.set_xlabel("time (UTC)")
        ax.grid(alpha=0.3)

    # 1. Latency
    ax = axes[0][0]
    resp = {b: [r for r in grouped[b] if r["event"] == "response_sent"] for b in active}
    xs = [b for b in active if resp[b]]
    for p, style in ((50, "-o"), (95, "-s"), (99, "-^")):
        ax.plot(xs, [percentile([r["latency_ms"] for r in resp[b]], p) for b in xs], style, ms=4, label=f"P{p} latency")
    ax.plot(xs, [percentile([r["ttft_ms"] for r in resp[b]], 95) for b in xs], ":d", ms=4, label="TTFT P95")
    threshold_line(ax, "latency", "ms")
    ax.set_yscale("log")
    ax.set_ylabel("latency (ms, log scale)")
    status_text(ax, "latency", f"window P50 {summary['p50']:.0f} · P95 {summary['p95']:.0f} · "
                f"P99 {summary['p99']:.0f} · TTFT P95 {summary['ttft_p95']:.0f} ms")
    ax.set_title(panels["latency"]["title"], fontsize=13, fontweight="bold")
    minute_axis(ax)
    ax.legend(loc="lower right", fontsize=8)

    # 2. Traffic
    ax = axes[0][1]
    counts = [len([r for r in grouped.get(b, []) if r["event"] == "request_received"]) for b in buckets]
    ax.bar(buckets, counts, width=1 / 1440 * 0.8, color="#1f77b4", label="request_received / min")
    threshold_line(ax, "traffic", "req/min")
    ax.set_ylabel("requests per minute")
    status_text(ax, "traffic", f"{summary['requests']} requests · avg {summary['rate_per_minute']:.2f} req/min over window")
    ax.set_title(panels["traffic"]["title"], fontsize=13, fontweight="bold")
    minute_axis(ax)
    ax.set_ylim(0, max(counts + [1]) * 1.25)
    ax.legend(loc="center left", fontsize=8)

    # 3. Errors
    ax = axes[0][2]
    ax.plot(active, [error_rate_pct(grouped[b]) for b in active], "-o", ms=4, color="#d62728", label="error rate %")
    rs = [(b, retrieval_success_pct(grouped[b])) for b in active]
    ax.plot([b for b, v in rs if v is not None], [v for _, v in rs if v is not None], "-s", ms=4,
            color="#2ca02c", label="retrieval success %")
    threshold_line(ax, "errors", "%")
    ax.set_ylim(-5, 110)
    ax.set_ylabel("percent (%)")
    breakdown = ", ".join(f"{k}={v}" for k, v in summary["error_breakdown"].items()) or "none"
    rsp = summary["retrieval_success_pct"]
    status_text(ax, "errors", f"error rate {summary['error_rate_pct']:.2f}% ({summary['failed']}/{summary['requests']}) · "
                f"retrieval success {rsp:.1f}%\nerror_type breakdown: {breakdown}" if rsp is not None else "no data")
    ax.set_title(panels["errors"]["title"], fontsize=13, fontweight="bold")
    minute_axis(ax)
    ax.legend(loc="center right", fontsize=8)

    # 4. Cost
    ax = axes[1][0]
    ax.bar(active, [sum(r.get("cost_usd", 0) for r in resp[b]) for b in active], width=1 / 1440 * 0.8,
           color="#9467bd", label="cost_usd / min")
    ax.set_ylabel("cost per minute (USD)")
    ax2 = ax.twinx()
    running, cum = 0.0, []
    for b in active:
        running += sum(r.get("cost_usd", 0) for r in resp[b])
        cum.append(running)
    ax2.plot(active, cum, "-", color="#8c564b", label="cumulative cost (USD)")
    threshold_line(ax2, "cost", "USD")
    ax2.set_ylabel("cumulative cost (USD)")
    ax2.set_ylim(0, panels["cost"]["threshold"]["value"] * 1.15)
    status_text(ax, "cost", f"total ${summary['cost_total']:.4f} in window")
    ax.set_title(panels["cost"]["title"], fontsize=13, fontweight="bold")
    minute_axis(ax)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center right", fontsize=8)

    # 5. Tokens
    ax = axes[1][1]
    names = ["tokens_in", "tokens_out"]
    values = [summary["tokens_in"], summary["tokens_out"]]
    bars = ax.bar(names, values, color=["#17becf", "#ff7f0e"])
    for bar, v in zip(bars, values):
        ax.annotate(f"{v:,}", (bar.get_x() + bar.get_width() / 2, v), ha="center", va="bottom", fontsize=11)
    threshold_line(ax, "tokens", "tokens")
    ax.set_ylabel("tokens (sum over window)")
    ax.set_ylim(0, panels["tokens"]["threshold"]["value"] * 1.15)
    status_text(ax, "tokens", f"in {summary['tokens_in']:,} · out {summary['tokens_out']:,} tokens")
    ax.set_title(panels["tokens"]["title"], fontsize=13, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="center right", fontsize=8)

    # 6. Quality
    ax = axes[1][2]
    xs = [b for b in active if resp[b]]
    ax.plot(xs, [mean(r["quality_score"] for r in resp[b]) for b in xs], "-o", ms=4, color="#2ca02c",
            label="mean quality_score / min")
    threshold_line(ax, "quality", "")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("quality score (0–1)")
    qm = summary["quality_mean"]
    status_text(ax, "quality", f"window mean {qm:.3f}" if qm is not None else "no data")
    ax.set_title(panels["quality"]["title"], fontsize=13, fontweight="bold")
    minute_axis(ax)
    ax.legend(loc="lower right", fontsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def print_summary(cfg: dict, summary: dict, start: datetime, end: datetime) -> None:
    print(f"{cfg['title']} | window {start:%Y-%m-%d %H:%M:%S} → {end:%H:%M:%S} UTC "
          f"({start.astimezone(VN_TZ):%H:%M} → {end.astimezone(VN_TZ):%H:%M} UTC+7)")
    rsp = summary["retrieval_success_pct"]
    details = {
        "latency": f"P50 {summary['p50']:.0f} / P95 {summary['p95']:.0f} / P99 {summary['p99']:.0f} ms, TTFT P95 {summary['ttft_p95']:.0f} ms",
        "traffic": f"{summary['requests']} requests, {summary['rate_per_minute']:.2f} req/min",
        "errors": f"error {summary['error_rate_pct']:.2f}% ({summary['failed']} failed), retrieval success "
                  + (f"{rsp:.1f}%" if rsp is not None else "n/a"),
        "cost": f"total ${summary['cost_total']:.6f}",
        "tokens": f"in {summary['tokens_in']:,} / out {summary['tokens_out']:,}",
        "quality": f"mean {summary['quality_mean']}",
    }
    values = panel_values(summary)
    print(f"{'panel':<9} {'value':>12} {'threshold':<24} {'status':<8} details")
    for panel in cfg["panels"]:
        th = panel["threshold"]
        ok = passes(values[panel["id"]], th["operator"], th["value"])
        sign = "<=" if th["operator"] == "lte" else ">="
        v = values[panel["id"]]
        print(f"{panel['id']:<9} {('n/a' if v is None else f'{v:,.4g}'):>12} "
              f"{th['aggregation'] + ' ' + sign + ' ' + format(th['value'], ','):<24} "
              f"{ {True: 'OK', False: 'BREACH', None: 'NO DATA'}[ok]:<8} {details[panel['id']]}")


def build_once(config: Path, logs: Path, output: Path, now: bool) -> dict:
    cfg = load_config(config)
    records = load_records(logs)
    end = datetime.now(timezone.utc) if now else None
    window, start, end = filter_window(records, cfg["time_range_minutes"], end)
    summary = summarize(window, cfg["time_range_minutes"])
    render(cfg, window, start, end, summary, output)
    print_summary(cfg, summary, start, end)
    print(f"saved {output}")
    return summary


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--now", action="store_true", help="end the window at the current time instead of the newest record")
    parser.add_argument("--watch", action="store_true", help="re-render every refresh_seconds")
    args = parser.parse_args()

    build_once(args.config, args.logs, args.output, args.now)
    if args.watch:
        refresh = load_config(args.config)["refresh_seconds"]
        while True:
            time.sleep(refresh)
            build_once(args.config, args.logs, args.output, args.now)


if __name__ == "__main__":
    main()
