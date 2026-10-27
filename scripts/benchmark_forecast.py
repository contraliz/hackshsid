"""Backtest the legacy (oracle-fed) forecast against ForecasterV2.

Runs the same realistic traffic trace under both forecast controllers, joins
each issued forecast with the demand that actually materialised, and reports
accuracy, bias, and upper-bound calibration. Writes results/forecast-v2/.

Usage:  python scripts/benchmark_forecast.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.dynamic_simulation import run_dynamic_comparison  # noqa: E402

SEEDS = (2026, 2028, 7)
HORIZONS = (5, 10, 15, 20, 30, 40)
CONFIDENCE = 0.90


def _pinball(actual: float, upper: float, quantile: float = CONFIDENCE) -> float:
    delta = actual - upper
    return quantile * delta if delta > 0 else (quantile - 1.0) * delta


def evaluate(seed: int) -> dict:
    result = run_dynamic_comparison({"nodes": 32, "gpus_per_node": 8, "seed": seed,
                                     "trace_source": "realistic"})
    trace = {row["minute"]: row for row in result["policies"]["forecast_v2"]["state_trace"]}
    fleet = result["fleet_gpus"]
    report = {"seed": seed, "requests": result["requests_generated"],
              "offered_peak_gpus": result["offered_peak_gpus"], "fleet_gpus": fleet,
              "controllers": {}}
    for name in ("always_on", "reactive", "forecast", "forecast_v2"):
        metrics = result["policies"][name]["metrics"]
        report["controllers"][name] = {
            "requests_waited": metrics["requests_waited"],
            "p95_wait_minutes": metrics["p95_wait_minutes"],
            "mean_wait_minutes": metrics["mean_wait_minutes"],
            "rejected": metrics["requests_rejected"],
            "completed": metrics["requests_completed"],
            "flexible_gpu_hours_unmet": metrics["flexible_gpu_hours_unmet"],
            "flexible_deadlines_met": metrics["flexible_jobs_deadline_met"],
            "facility_kwh": metrics["facility_kwh"],
            "peak_active_nodes": metrics["peak_active_nodes"],
            "max_readiness_shortfall_gpus": metrics["max_readiness_capacity_shortfall_gpus"],
        }

    for engine_policy in ("forecast", "forecast_v2"):
        debug = result["policies"][engine_policy]["replay"].get("forecast_debug", [])
        per_horizon = {h: {"errors": [], "covered": 0, "widths": [], "pinball": []}
                       for h in HORIZONS}
        for record in debug:
            issue = record["minute"]
            for horizon in HORIZONS:
                future = trace.get(issue + horizon)
                if future is None:
                    continue
                actual = future["offered_gpus"] + future["flexible_gpus"]
                predicted = record["predicted"][horizon]
                upper = record["upper"][horizon]
                per_horizon[horizon]["errors"].append(actual - predicted)
                per_horizon[horizon]["covered"] += int(actual <= upper + 1e-9)
                per_horizon[horizon]["widths"].append(upper - predicted)
                per_horizon[horizon]["pinball"].append(_pinball(actual, upper))
        summary = {}
        for horizon, bucket in per_horizon.items():
            errors = bucket["errors"]
            if not errors:
                continue
            summary[str(horizon)] = {
                "samples": len(errors),
                "bias_gpus": round(statistics.fmean(errors), 2),
                "mae_gpus": round(statistics.fmean(abs(e) for e in errors), 2),
                "rmse_gpus": round((statistics.fmean(e * e for e in errors)) ** 0.5, 2),
                "p90_abs_error_gpus": round(sorted(abs(e) for e in errors)[int(0.9 * len(errors))], 2),
                "coverage": round(bucket["covered"] / len(errors), 3),
                "mean_upper_width_gpus": round(statistics.fmean(bucket["widths"]), 2),
                "pinball_loss": round(statistics.fmean(bucket["pinball"]), 3),
            }
        report["controllers"][engine_policy]["forecast_accuracy"] = summary
    return report


def main() -> int:
    reports = [evaluate(seed) for seed in SEEDS]
    out_dir = ROOT / "results" / "forecast-v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "backtest.json").write_text(json.dumps(reports, indent=2))

    lines = ["# Forecast backtest: legacy oracle model vs ForecasterV2", "",
             "Same realistic traffic trace and same controller policy; only the forecast",
             "engine differs. `forecast` reads hidden durations, running end minutes and",
             "the LP hourly rate vector. `forecast_v2` receives none of those.", "",
             "Metrics are GPU-level: predicted total demand vs realised offered + flexible",
             "demand at the stated horizon. Coverage is the share of realised demand below",
             "the forecast's upper bound (target 0.90).", ""]
    for report in reports:
        lines.append(f"## Seed {report['seed']} ({report['requests']} requests, "
                     f"peak offered {report['offered_peak_gpus']} GPUs, fleet {report['fleet_gpus']})")
        lines.append("")
        lines.append("| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        for horizon in HORIZONS:
            for engine in ("forecast", "forecast_v2"):
                row = report["controllers"][engine]["forecast_accuracy"].get(str(horizon))
                if not row:
                    continue
                lines.append(f"| {horizon} | {engine} | {row['bias_gpus']:+.1f} | {row['mae_gpus']:.1f} | "
                             f"{row['rmse_gpus']:.1f} | {row['p90_abs_error_gpus']:.1f} | "
                             f"{row['coverage']:.2f} | {row['mean_upper_width_gpus']:.1f} |")
        lines.append("")
        lines.append("| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for name, row in report["controllers"].items():
            lines.append(f"| {name} | {row['requests_waited']} | {row['p95_wait_minutes']:.1f} | "
                         f"{row['rejected']} | {row['flexible_gpu_hours_unmet']:.1f} | "
                         f"{row['flexible_deadlines_met']} | {row['facility_kwh']:.1f} |")
        lines.append("")
    (out_dir / "backtest.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
