"""Compare the 2026-10-26 immediate-warm policy on saved identical seeds."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.dynamic_simulation import run_dynamic_comparison


BASELINE_PATH = ROOT / "results" / "instant-warm-policy-baseline-2026.json"
OUTPUT_PATH = ROOT / "results" / "instant-warm-policy-comparison-2026.json"
REPORT_PATH = ROOT / "results" / "instant-warm-policy-comparison-2026.md"
POLICIES = ("always_on", "reactive", "forecast")


def trace_hash(requests: list[dict]) -> str:
    text = "\n".join("|".join(map(str, (
        item["id"], item["tier"], item["arrival_minute"], item["gpus"], item["duration_minutes"]
    ))) for item in requests)
    return hashlib.sha256(text.encode()).hexdigest()


def summarize(result: dict) -> dict:
    output = {
        "requests_generated": result["requests_generated"],
        "request_trace_sha256": trace_hash(result["policies"]["forecast"]["replay"]["requests"]),
        "offered_peak_gpus": result["offered_peak_gpus"],
        "realized_peak_snapshot": result["realized_peak_snapshot"],
        "policies": {},
    }
    for name in POLICIES:
        policy = result["policies"][name]
        frames = policy["replay"]["frames"]
        warm = [frame["states"].count("warm") for frame in frames]
        interval = frames[60:120]
        at_0110 = frames[70]
        metrics = policy["metrics"]
        output["policies"][name] = {
            "metrics": metrics,
            "warm_ready_zero_minutes": sum(count == 0 for count in warm),
            "warm_ready_min_nodes": min(warm, default=0),
            "warm_ready_max_nodes": max(warm, default=0),
            "active_spare_01_02_min_gpus": min((f["active_spare_gpus"] for f in interval), default=0),
            "requests_arrived_01_02": sum(60 <= r["arrival_minute"] < 120
                                           for r in policy["replay"]["requests"]),
            "requests_waited_01_02": sum(60 <= r["arrival_minute"] < 120
                                         and r["started_at_minute"] is not None
                                         and r["started_at_minute"] > r["arrival_minute"]
                                         for r in policy["replay"]["requests"]),
            "at_0110": {
                "active_nodes": at_0110["states"].count("active"),
                "warm_ready_nodes": at_0110["states"].count("warm"),
                "booting_nodes": at_0110["states"].count("booting"),
                "off_nodes": at_0110["states"].count("off"),
                "active_spare_gpus": at_0110["active_spare_gpus"],
                "dispatchable_capacity_gpus": at_0110["dispatchable_capacity_gpus"],
                "queued_requests": at_0110.get("queued_requests"),
            },
            "hourly_grid_costs": policy["hourly_grid_costs"],
        }
    return output


def main() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    cases = [
        ("normal_default", 32, "normal"),
        ("low_default", 32, "low"),
        ("high_default", 32, "high"),
        ("constrained_high", 12, "high"),
    ]
    by_name = {case["case"]: case for case in baseline["cases"]}
    after = []
    for name, nodes, profile in cases:
        result = run_dynamic_comparison({
            "seed": 2026, "nodes": nodes, "gpus_per_node": 8,
            "traffic_profile": profile, "headroom_nodes": 0, "bursts": True,
            "warm_overhead_nodes": 2,
        })
        observed = summarize(result)
        prior = by_name[name]
        if observed["request_trace_sha256"] != prior["request_trace_sha256"]:
            raise RuntimeError(f"Request trace changed for {name}; refusing a non-identical comparison.")
        after.append({"case": name, "nodes": nodes, "traffic_profile": profile,
                      "before": prior, "after": observed})
    payload = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Direct run_dynamic_comparison calls against saved pre-change summary; same seeds, request traces, fleet and bursts; Forecast warm-stock target changed from 1 to 2 by default.",
        "baseline_file": str(BASELINE_PATH.relative_to(ROOT)),
        "policy": {
            "warm_to_active_minutes": 0,
            "cold_to_warm_minutes": 20,
            "default_warm_stock_target_nodes": 2,
            "runtime_priority": "real-time first; accepted flexible work uses remaining active capacity and reports deadline shortfall",
        },
        "cases": after,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Immediate-warm policy: same-input comparison (2026-10-26)",
        "",
        f"Captured {payload['captured_at_utc']}. These are same-seed, same-request-trace comparisons against the pre-change saved baseline. The revised scenario uses 0-minute warm promotion and a default two-node warm-stock target; cold boot remains 20 minutes.",
        "",
        "| Case | Controller | Waited requests (before → after) | Mean / p95 wait min (before → after) | Flexible GPU·h delivered (before → after) | Flex deadline misses (before → after) | Facility kWh (before → after) | Grid cost CNY (before → after) | Warm-ready zero minutes (before → after) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in after:
        for name in POLICIES:
            before = case["before"]["policies"][name]["metrics"]
            current = case["after"]["policies"][name]
            final = current["metrics"]
            lines.append(
                f"| {case['case']} | {name} | {before['requests_waited']} → {final['requests_waited']} | "
                f"{before['mean_wait_minutes']} / {before['p95_wait_minutes']} → {final['mean_wait_minutes']} / {final['p95_wait_minutes']} | "
                f"{before['flexible_gpu_hours_delivered']} → {final['flexible_gpu_hours_delivered']} | "
                f"{before['flexible_deadline_misses']} → {final['flexible_deadline_misses']} | "
                f"{before['facility_kwh']} → {final['facility_kwh']} | {before['cost_cny']} → {final['cost_cny']} | "
                f"{case['before'].get('forecast_zero_warm_ready_minute_count', 'n/a')} → {current['warm_ready_zero_minutes']} |"
            )
    lines.extend(["", "## Trace and window notes", ""])
    for case in after:
        current = case["after"]
        forecast = current["policies"]["forecast"]
        lines.append(
            f"- **{case['case']}**: {current['requests_generated']} requests, trace SHA-256 `{current['request_trace_sha256']}`, "
            f"offered peak {current['offered_peak_gpus']} GPUs. Forecast warm-ready zero minutes: "
            f"{case['before'].get('forecast_zero_warm_ready_minute_count', 'n/a')} → {forecast['warm_ready_zero_minutes']}; "
            f"minimum active spare in 01:00–02:00: {case['before'].get('forecast_interval60_119_min_active_spare_gpus', 'n/a')} → {forecast['active_spare_01_02_min_gpus']} GPUs. "
            f"At 01:10: {forecast['at_0110']} ."
        )
    lines.extend([
        "",
        "A zero wait/zero flex miss in a specific seeded run is an observation, not a cross-seed guarantee. Warm stock can be depleted during sustained peaks; cold replacement takes 20 minutes. `grid_cost` is an illustrative hourly tariff proxy, not a site bill. Each after-case stores 24 tariff rows per controller in the JSON artifact.",
        "",
        f"Machine-readable rows: [{OUTPUT_PATH.name}]({OUTPUT_PATH.name}).",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_PATH)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
