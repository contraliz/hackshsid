"""Tests for the information-restricted forecaster and the realistic trace."""
from __future__ import annotations

import math
import statistics

import pytest

from backend.dynamic_simulation import (Node, _forecast_v2_curve, _offered_gpu_trace,
                                        run_dynamic_comparison)
from backend.forecast_v2 import ForecasterV2, HORIZON, MIN_RESIDUALS
from backend.traffic_realistic import generate_realistic_requests


def test_realistic_trace_is_seeded_heavy_tailed_and_overdispersed():
    first = generate_realistic_requests(2026, gpus_per_node=8, nodes=32)
    second = generate_realistic_requests(2026, gpus_per_node=8, nodes=32)
    assert first == second
    assert len(first) > 500
    assert first == sorted(first, key=lambda r: (r["arrival"], r["id"]))
    assert {r["class"] for r in first} == {"interactive", "batch"}
    # Heavy tails: most jobs are small, but a real tail exists.
    sizes = [r["gpus"] for r in first]
    durations = [r["duration"] for r in first]
    assert statistics.median(sizes) <= 2
    assert max(sizes) >= 16
    assert statistics.median(durations) <= 12 < max(durations)
    # Over-dispersion: minute-level concurrency is far burstier than Poisson.
    offered = _offered_gpu_trace(first)
    mean = statistics.fmean(offered)
    variance = statistics.pvariance(offered)
    assert variance / max(mean, 1e-9) > 3.0


def test_v2_forecast_ignores_hidden_duration_and_end_time():
    """Two worlds that differ only in fields a controller cannot see must tie."""
    def build(duration: int, end_minute: int):
        statuses = {
            "run-1": {"class": "interactive", "gpus": 2, "arrival": 10, "start": 12,
                      "duration": duration},
            "wait-1": {"class": "batch", "gpus": 4, "arrival": 20, "duration": duration},
        }
        running = {"run-1": {"gpus": 2, "start": 12, "end": end_minute, "nodes": [(0, 2)]}}
        forecaster = ForecasterV2(8, 8, 0, 20)
        for _ in range(40):
            forecaster.observe_completion_for("interactive", 5)
        return _forecast_v2_curve(forecaster, 30, running, ["wait-1"], statuses,
                                  [Node("active"), Node("warm")], {"jobs": [], "hourly_rates": []},
                                  [], 8, HORIZON)

    short = build(duration=3, end_minute=15)
    long = build(duration=900, end_minute=9999)
    assert short == long


def test_survival_is_censoring_aware_and_monotone():
    forecaster = ForecasterV2(8, 32)
    for lifetime in (2, 3, 3, 4, 9):
        forecaster.observe_completion_for("batch", lifetime)
    forecaster.censored_ages = {"interactive": [], "batch": [40, 55]}
    forecaster.survival_key.clear()
    survival = forecaster.survival("batch")
    assert survival[0] == pytest.approx(1.0)
    assert all(survival[i] >= survival[i + 1] - 1e-12 for i in range(len(survival) - 1))
    assert 0.0 < survival[10] < 1.0
    # Long-running censored jobs keep the tail alive instead of being forgotten.
    assert forecaster.mean_duration("batch") > 10


def test_conformal_margin_switches_after_enough_matured_residuals():
    forecaster = ForecasterV2(8, 32)
    predicted = [100.0] * (HORIZON + 1)
    _, margin, source, samples, _ = forecaster._upper_bound(predicted)
    assert source == "cold_start_fallback"
    assert samples == 0
    assert margin >= 20.0

    for _ in range(MIN_RESIDUALS + 5):
        for bucket in forecaster.residuals:
            bucket.append(15.0)
    _, margin, source, samples, margins = forecaster._upper_bound(predicted)
    assert source == "online_conformal_q90"
    assert samples >= MIN_RESIDUALS
    assert margin == pytest.approx(15.0)
    assert margins[0] == pytest.approx(15.0)


def test_realistic_run_produces_finite_v2_forecasts_and_service_metrics():
    result = run_dynamic_comparison({"nodes": 40, "gpus_per_node": 8, "seed": 2026,
                                     "trace_source": "realistic"})
    policy = result["policies"]["forecast_v2"]
    assert len(policy["replay"]["frames"]) == 1440
    debug = policy["replay"]["forecast_debug"]
    assert len(debug) > 200
    for record in debug[:50]:
        assert all(math.isfinite(value) for value in record["predicted"])
        assert all(math.isfinite(value) for value in record["upper"])
        assert all(upper >= predicted - 1e-9
                   for predicted, upper in zip(record["predicted"], record["upper"]))
    metrics = policy["metrics"]
    assert metrics["requests_completed"] > 0
    assert math.isfinite(metrics["mean_wait_minutes"])
    # The forecast must never claim knowledge of future arrivals: two traces that
    # share a prefix must produce identical frames over that prefix.
    prefix = [{"id": "early", "class": "interactive", "arrival": 20, "gpus": 2,
               "duration": 10, "latency": 2}]
    later = [{"id": f"later-{i}", "class": "batch", "arrival": 600, "gpus": 4,
              "duration": 20, "latency": 30} for i in range(10)]
    base = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8, "request_trace": prefix,
                                   "flexible_jobs": []})
    extended = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8,
                                       "request_trace": prefix + later, "flexible_jobs": []})
    assert (base["policies"]["forecast_v2"]["replay"]["frames"][:600]
            == extended["policies"]["forecast_v2"]["replay"]["frames"][:600])
