"""Minute-resolution, reproducible node-state simulation for synthetic requests.

This is a comparison model, not a controller. Traffic, power coefficients and
forecast calibration are synthetic scenario assumptions.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math
import random
from typing import Any

from .data import JOBS, RENEWABLE_AVAILABLE, build_case, validate_case
from .scheduler import solve_lp
from .forecast_v2 import ForecasterV2, FlexCommitment, NodeView, QueuedJob, RunningJob
from .traffic_realistic import generate_realistic_requests

MINUTES_PER_DAY = 24 * 60
BUCKET = 5
CLASSES = {
    "interactive": {"rate_per_5m": 6.0, "gpu": (1, 2), "duration": (2, 5, 8), "latency": 2},
    "batch": {"rate_per_5m": 2.0, "gpu": (2, 4), "duration": (5, 15, 30), "latency": 30},
}
TOU_PRICE_CNY = [0.38648119 if h < 8 else 0.83855171 if h in (10, 11, 15, 16, 17, 18, 19, 20, 21) else 0.62185675 for h in range(24)]
GRID_CO2_KG_KWH = 0.55
WARM_START_MINUTES = 0
COLD_BOOT_TO_WARM_MINUTES = 20
COLD_TO_ACTIVE_MINUTES = COLD_BOOT_TO_WARM_MINUTES + WARM_START_MINUTES
FORECAST_HORIZON_MINUTES = 2 * COLD_TO_ACTIVE_MINUTES
MARGIN_HISTORY_WINDOWS_REQUIRED = 28
MARGIN_QUANTILE = 0.95
TRAFFIC_PROFILES = {"low": 0.5, "normal": 1.0, "high": 2.0}
TRACE_SOURCES = ("realistic", "legacy")
FORECAST_POLICIES = ("forecast", "forecast_v2")
DEFAULT_WARM_OVERHEAD_NODES = 2


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    limit, product, count = math.exp(-mean), 1.0, 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _tod(minute: int) -> float:
    hour = minute // 60
    return 0.35 if hour < 6 else 0.6 if hour < 9 else 1.0 if hour < 17 else 1.5 if hour < 22 else 0.7


def generate_requests(seed: int, *, burst: bool = True, traffic_multiplier: float = 1.0) -> list[dict[str, Any]]:
    """Generate one seeded day; service durations are fixed on arrival."""
    if isinstance(traffic_multiplier, bool) or not isinstance(traffic_multiplier, (int, float)) or not math.isfinite(traffic_multiplier) or traffic_multiplier <= 0:
        raise ValueError("Traffic multiplier must be a positive finite number.")
    rng = random.Random(seed)
    burst_starts = set()
    if burst and rng.random() < 0.25:
        burst_starts.add(rng.randrange(0, MINUTES_PER_DAY - 15))
    records = []
    for start in range(0, MINUTES_PER_DAY, BUCKET):
        burst_multiplier = 3.0 if any(b <= start < b + 15 for b in burst_starts) else 1.0
        for name, cfg in CLASSES.items():
            n = _poisson(rng, cfg["rate_per_5m"] * _tod(start) * burst_multiplier * traffic_multiplier)
            for _ in range(n):
                gpus = rng.randint(*cfg["gpu"])
                # Configuration stores min/typical/max. random.triangular is
                # (low, high, mode), so the typical value is the mode.
                minimum, typical, maximum = cfg["duration"]
                duration = round(rng.triangular(minimum, maximum, typical))
                records.append({"id": f"{name}-{len(records)}", "class": name,
                                "arrival": start + rng.randrange(BUCKET), "gpus": gpus,
                                "duration": max(1, duration), "latency": cfg["latency"]})
    return sorted(records, key=lambda r: (r["arrival"], r["id"]))


def _offered_gpu_trace(requests: list[dict[str, Any]]) -> list[int]:
    """Unconstrained offered concurrency: independent from scheduler service."""
    delta = [0] * (MINUTES_PER_DAY + 1)
    for r in requests:
        delta[r["arrival"]] += r["gpus"]
        end = min(MINUTES_PER_DAY, r["arrival"] + r["duration"])
        delta[end] -= r["gpus"]
    running, result = 0, []
    for t in range(MINUTES_PER_DAY):
        running += delta[t]
        result.append(running)
    return result


def _workload_gpu_minutes_per_request() -> dict[str, float]:
    """Synthetic class mean GPU-minutes/request from the configured generator."""
    def cdf(x: float, low: float, high: float, mode: float) -> float:
        if x <= low:
            return 0.0
        if x >= high:
            return 1.0
        if x <= mode:
            return (x - low) ** 2 / ((high - low) * (mode - low))
        return 1 - (high - x) ** 2 / ((high - low) * (high - mode))

    factors = {}
    for name, cfg in CLASSES.items():
        mean_gpus = (cfg["gpu"][0] + cfg["gpu"][1]) / 2
        minimum, typical, maximum = cfg["duration"]
        # Match Python's round() on the continuous triangular draw by summing
        # each integer duration's probability mass over its rounding bin.
        mean_duration = sum(
            duration * (cdf(duration + 0.5, minimum, maximum, typical)
                        - cdf(duration - 0.5, minimum, maximum, typical))
            for duration in range(minimum, maximum + 1)
        )
        factors[name] = mean_gpus * mean_duration
    return factors


def _rounded_duration_distribution(name: str) -> dict[int, float]:
    """Return the exact integer-minute probability mass after Python round()."""
    minimum, typical, maximum = CLASSES[name]["duration"]

    def cdf(x: float) -> float:
        if x <= minimum:
            return 0.0
        if x >= maximum:
            return 1.0
        if x <= typical:
            return (x - minimum) ** 2 / ((maximum - minimum) * (typical - minimum))
        return 1 - (maximum - x) ** 2 / ((maximum - minimum) * (maximum - typical))

    return {
        duration: cdf(duration + 0.5) - cdf(duration - 0.5)
        for duration in range(minimum, maximum + 1)
    }


def _expected_future_arrival_concurrency(rates: dict[str, float], minute: int, horizon: int,
                                         work_factors: dict[str, float]) -> list[float]:
    """Expected GPU concurrency from not-yet-arrived requests only.

    For each future minute, convolve causal requests/minute with the rounded
    service-duration survival distribution. Existing running/queued jobs are
    intentionally handled separately, so their GPU-minutes are not counted a
    second time as steady-state lambda × E[GPU-minutes/request].
    """
    horizon = max(0, int(horizon))
    demand = [0.0] * (horizon + 1)
    default_factors = _workload_gpu_minutes_per_request()
    tod_now = max(_tod(minute), 1e-9)
    for name, cfg in CLASSES.items():
        distribution = _rounded_duration_distribution(name)
        mean_gpus = (cfg["gpu"][0] + cfg["gpu"][1]) / 2
        factor_scale = work_factors[name] / max(default_factors[name], 1e-9)
        survival = [sum(probability for duration, probability in distribution.items() if duration > age)
                    for age in range(horizon + 1)]
        rate = rates.get(name, 0.0)
        for offset in range(1, horizon + 1):
            future_arrival_minute = minute + offset
            if future_arrival_minute >= MINUTES_PER_DAY:
                continue
            scaled_rate = rate * _tod(future_arrival_minute) / tod_now
            demand[offset] += scaled_rate * mean_gpus * factor_scale * survival[0]
            # Requests arriving earlier in this forecast window remain active
            # according to their own duration survival probability.
            for arrival_offset in range(1, offset):
                arrival_minute = minute + arrival_offset
                if arrival_minute >= MINUTES_PER_DAY:
                    continue
                arrival_rate = rate * _tod(arrival_minute) / tod_now
                demand[offset] += (arrival_rate * mean_gpus * factor_scale
                                   * survival[offset - arrival_offset])
    return demand


def _arrival_rate_forecasts(requests: list[dict[str, Any]], alpha: float = 0.3,
                            *, generator_prior: bool = True, generator_rate_multiplier: float = 1.0) -> list[dict[str, float]]:
    """EWMA arrival-rate forecasts at each bucket start, using completed buckets only.

    Rates are requests/minute. The initial state is the declared synthetic
    generator rate at the start of the day; after that the user's specified
    EWMA update uses only arrivals from the most recently completed bucket.
    """
    bucket_count = MINUTES_PER_DAY // BUCKET
    arrivals = [{name: 0 for name in CLASSES} for _ in range(bucket_count)]
    for request in requests:
        bucket = request["arrival"] // BUCKET
        if 0 <= bucket < bucket_count and request["class"] in arrivals[bucket]:
            arrivals[bucket][request["class"]] += 1
    rates = ({name: cfg["rate_per_5m"] * _tod(0) * generator_rate_multiplier / BUCKET for name, cfg in CLASSES.items()}
             if generator_prior else {name: 0.0 for name in CLASSES})
    forecasts = []
    for bucket in range(bucket_count):
        forecasts.append(dict(rates))
        for name in CLASSES:
            observed_rate = arrivals[bucket][name] / BUCKET
            rates[name] = alpha * observed_rate + (1 - alpha) * rates[name]
    return forecasts


def _expected_realtime_gpu_demand(rates: dict[str, float], minute: int,
                                  horizon_minute: int, work_factors: dict[str, float]) -> float:
    """Compatibility wrapper returning new-arrival concurrency at a future minute."""
    offset = max(0, horizon_minute - minute)
    return _expected_future_arrival_concurrency(rates, minute, offset, work_factors)[offset]


def _known_running_gpu_demand(running: dict[str, dict[str, Any]], horizon_minute: int) -> int:
    return sum(job["gpus"] for job in running.values() if job["end"] > horizon_minute)


def _known_queued_gpu_pressure(waiting: deque[str], statuses: dict[str, dict[str, Any]],
                               bridge_minutes: int) -> float:
    """Approximate queued-work concurrency by spreading known GPU-minutes over the bridge.

    Queue entries are already-observed requests and are not re-counted in the
    future-arrival EWMA. This transparent occupancy approximation is not a
    dispatch simulation; it estimates capacity needed to work through the
    current backlog during the warm-vs-cold startup window.
    """
    if not waiting or bridge_minutes <= 0:
        return 0.0
    backlog_gpu_minutes = sum(
        statuses[rid]["gpus"] * min(statuses[rid]["duration"], bridge_minutes)
        for rid in waiting
    )
    return backlog_gpu_minutes / bridge_minutes


def _queue_priority_ids(waiting: deque[str], statuses: dict[str, dict[str, Any]], minute: int,
                        queue_policy: str) -> list[str]:
    """Stable forecast ordering matching the actual dispatch policy's priorities."""
    ids = list(waiting)
    if queue_policy == "fifo_next_fit":
        return sorted(ids, key=lambda rid: (statuses[rid]["arrival"], rid))
    aged = sorted((rid for rid in ids if statuses[rid]["class"] == "batch"
                   and minute - statuses[rid]["arrival"] >= 15),
                  key=lambda rid: (statuses[rid]["arrival"], rid))
    ordered = sorted(ids, key=lambda rid: (
        0 if statuses[rid]["class"] == "interactive" else 1,
        statuses[rid]["arrival"], rid,
    ))
    if aged:
        head = aged[0]
        return [head] + [rid for rid in ordered if rid != head]
    return ordered


def _queued_workload_profile(waiting: deque[str], statuses: dict[str, dict[str, Any]],
                             running: dict[str, dict[str, Any]], nodes: list["Node"],
                             minute: int, horizon: int, gpus_per_node: int,
                             flex_plan: dict[str, Any], future_arrivals: list[float],
                             queue_policy: str) -> tuple[list[float], dict[str, int], int]:
    """Place known queued jobs at their earliest non-preemptive feasible slot.

    The planning capacity uses actual active/warming/warm/booting ETAs and
    permits currently off nodes only from minute 25 onward, when a cold start
    initiated now could be active. Per-request GPU sizes and durations are
    packed against contemporaneous running, flexible and expected new-arrival
    demand. The forecast does not expose the synthetic future trace.
    """
    load = [0.0] * (horizon + 1)
    starts: dict[str, int] = {}
    unplaced = 0
    available = []
    for offset in range(horizon + 1):
        current = sum(1 for node in nodes if node.state == "active")
        current += sum(1 for node in nodes if node.state == "warming" and node.remaining <= offset)
        current += sum(1 for node in nodes if node.state == "warm" and offset >= WARM_START_MINUTES)
        current += sum(1 for node in nodes if node.state == "booting"
                       and node.remaining + WARM_START_MINUTES <= offset)
        if offset >= COLD_TO_ACTIVE_MINUTES:
            current += sum(1 for node in nodes if node.state == "off")
        available.append(current * gpus_per_node)

    running_load = [sum(job["gpus"] for job in running.values()
                        if job["end"] > minute + offset) for offset in range(horizon + 1)]
    flex_load = [_flex_rate_at(flex_plan["hourly_rates"], minute + offset)
                 for offset in range(horizon + 1)]
    for rid in _queue_priority_ids(waiting, statuses, minute, queue_policy):
        request = statuses[rid]
        duration = min(request["duration"], horizon + 1)
        possible = False
        latest_start = max(0, horizon - duration + 1)
        for start in range(latest_start + 1):
            fits = True
            for offset in range(start, start + duration):
                occupied = running_load[offset] + flex_load[offset] + future_arrivals[offset] + load[offset]
                if available[offset] - occupied + 1e-9 < request["gpus"]:
                    fits = False
                    break
            if fits:
                starts[rid] = start
                for offset in range(start, start + duration):
                    load[offset] += request["gpus"]
                possible = True
                break
        if not possible:
            unplaced += 1
    return load, starts, unplaced


def _forecast_margin(window_errors: list[float], forecast_peak: float,
                     margin_fraction: float, margin_floor_gpus: float = 4.0) -> tuple[float, str]:
    """Use matured prior startup-window errors when available, otherwise the labeled fallback."""
    if len(window_errors) >= MARGIN_HISTORY_WINDOWS_REQUIRED:
        ordered = sorted(max(0.0, float(error)) for error in window_errors)
        index = max(0, math.ceil(MARGIN_QUANTILE * len(ordered)) - 1)
        return ordered[min(index, len(ordered) - 1)], "matured_synthetic_window_q95"
    return max(margin_floor_gpus, margin_fraction * max(0.0, forecast_peak)), "manual_assumption_fallback"


def _warm_target(upper_demands: list[float], active_nodes: int, nodes: int,
                 gpus_per_node: int) -> dict[str, float | int]:
    """Unclipped adopted reserve target and independently reported shortfalls."""
    active_capacity = active_nodes * gpus_per_node
    peak_upper = max(upper_demands, default=0.0)
    target = math.ceil(max(0.0, peak_upper - active_capacity) / gpus_per_node)
    available_nonactive = max(0, nodes - active_nodes)
    return {
        "target_warm_nodes": target,
        "target_warm_fleet_shortfall_nodes": max(0, target - available_nonactive),
        "target_warm_realizable_nodes": min(target, available_nonactive),
        "peak_upper_demand_gpus": peak_upper,
        "peak_fleet_shortfall_gpus": max(0.0, peak_upper - nodes * gpus_per_node),
    }


def _readiness_shortfalls(upper_by_offset: list[tuple[int, float]], nodes: list["Node"],
                          gpus_per_node: int) -> tuple[float, int, float]:
    """Return peak warm-window shortfall, affected minute count, and pre-warm shortfall."""
    peak = 0.0
    affected = 0
    pre_warm_peak = 0.0
    for offset, upper in upper_by_offset:
        ready = _projected_active_capacity(nodes, offset, gpus_per_node)
        shortfall = max(0.0, upper - ready)
        if shortfall > 1e-9:
            peak = max(peak, shortfall)
            affected += 1
        if offset < COLD_TO_ACTIVE_MINUTES:
            pre_warm_peak = max(pre_warm_peak, shortfall)
    return peak, affected, pre_warm_peak


def _forecast_ready_nodes(nodes: list["Node"], minutes_ahead: int) -> int:
    """Count nodes already on an active-readiness path at the future offset."""
    return sum(
        node.state == "active"
        or (node.state == "warming" and node.remaining <= minutes_ahead)
        or (node.state == "booting" and node.remaining + WARM_START_MINUTES <= minutes_ahead)
        for node in nodes
    )


def _plan_active_readiness(nodes: list["Node"], upper_demand_by_offset: list[float],
                           gpus_per_node: int, warm_ready_floor: int = 1) -> dict[str, Any]:
    """Plan causal active readiness and preserve warm stock for near demand.

    Warm nodes can be promoted immediately. For targets at least one cold-start
    lead time away, issue cold boots first; for nearer gaps, promote warm nodes.
    Every node leaves its prior state as soon as an action is issued.
    """
    warm_started = 0
    cold_started = 0
    targets = [math.ceil(max(0.0, demand) / gpus_per_node) for demand in upper_demand_by_offset]
    for offset, target in enumerate(targets):
        if target <= _forecast_ready_nodes(nodes, offset):
            continue
        # For demand at least one cold-start lead time away, boot from OFF
        # first so ready standby remains available for nearer real-time work.
        if offset >= COLD_TO_ACTIVE_MINUTES:
            for node in nodes:
                if _forecast_ready_nodes(nodes, offset) >= target:
                    break
                if node.state == "off":
                    node.state, node.remaining, node.purpose = "booting", COLD_BOOT_TO_WARM_MINUTES, "activation"
                    node.idle = 0
                    cold_started += 1
        if offset < COLD_TO_ACTIVE_MINUTES:
            ready_warm = sum(node.state == "warm" for node in nodes)
            for node in nodes:
                if _forecast_ready_nodes(nodes, offset) >= target or ready_warm <= warm_ready_floor:
                    break
                if node.state == "warm":
                    node.state, node.remaining, node.purpose = "active", 0, None
                    node.idle = 0
                    warm_started += 1
                    ready_warm -= 1
        if offset >= COLD_TO_ACTIVE_MINUTES:
            for node in nodes:
                if _forecast_ready_nodes(nodes, offset) >= target:
                    break
                if node.state == "off":
                    node.state, node.remaining, node.purpose = "booting", COLD_BOOT_TO_WARM_MINUTES, "activation"
                    node.idle = 0
                    cold_started += 1
    projected_gpus = [_forecast_ready_nodes(nodes, offset) * gpus_per_node
                      for offset in range(len(targets))]
    gaps = [max(0.0, upper_demand_by_offset[offset] - projected_gpus[offset])
            for offset in range(len(targets))]
    early_gap = max(gaps[:max(1, COLD_TO_ACTIVE_MINUTES)], default=0.0)
    return {
        "target_active_nodes": targets,
        "peak_target_active_nodes": max(targets, default=0),
        "warm_nodes_started": warm_started,
        "cold_nodes_started": cold_started,
        "projected_active_gpus": projected_gpus,
        "readiness_gaps_gpus": gaps,
        "peak_readiness_gap_gpus": max(gaps, default=0.0),
        "readiness_gap_minutes": sum(gap > 1e-9 for gap in gaps),
        "pre_warm_active_gap_gpus": early_gap,
    }


@dataclass
class Node:
    state: str
    remaining: int = 0
    idle: int = 0
    used: int = 0
    purpose: str | None = None


def _validate(payload: dict[str, Any]) -> tuple[int, int, int, int]:
    def whole_number(value: Any, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a whole number.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a whole number.") from None
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError(f"{label} must be a whole number.")
        return int(number)

    nodes = whole_number(payload.get("nodes", 32), "Nodes")
    headroom_nodes = whole_number(payload.get("headroom_nodes", 0), "Headroom nodes")
    gpn = whole_number(payload.get("gpus_per_node", 8), "GPUs per node")
    seed = whole_number(payload.get("seed", 2026), "Seed")
    if not 2 <= nodes <= 64 or not 0 <= headroom_nodes <= 32 or nodes + headroom_nodes > 64 or not 1 <= gpn <= 16 or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Use 2–64 nodes before added headroom (64 total maximum), 0–32 added headroom nodes, 1–16 GPUs per node, and a nonnegative 32-bit seed.")
    return nodes + headroom_nodes, gpn, seed, headroom_nodes


def run_dynamic_comparison(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run identical offered requests under always-on, reactive, and forecast control."""
    payload = payload or {}
    n, gpn, seed, headroom_nodes = _validate(payload)
    traffic_profile = payload.get("traffic_profile", "normal")
    if not isinstance(traffic_profile, str) or traffic_profile not in TRAFFIC_PROFILES:
        raise ValueError("Traffic profile must be low, normal, or high.")
    traffic_multiplier = TRAFFIC_PROFILES[traffic_profile]
    explicit_trace = payload.get("request_trace") is not None
    trace_source = payload.get("trace_source", "realistic")
    if not isinstance(trace_source, str) or trace_source not in TRACE_SOURCES:
        raise ValueError("Trace source must be 'realistic' or 'legacy'.")
    try:
        alpha = float(payload.get("forecast_alpha", 0.3))
        margin_fraction = float(payload.get("margin_fraction", 0.15))
        margin_floor_gpus = float(payload.get("margin_floor_gpus", 4.0))
        min_active_fraction = float(payload.get("min_active_fraction", 0.25))
        warm_overhead_nodes = float(payload.get("warm_overhead_nodes", DEFAULT_WARM_OVERHEAD_NODES))
    except (TypeError, ValueError):
        raise ValueError("Forecast alpha and margin fraction must be numbers.") from None
    if (not 0.05 <= alpha <= 0.8 or not 0 <= margin_fraction <= 1
            or not math.isfinite(margin_floor_gpus) or margin_floor_gpus < 0
            or not 0 <= min_active_fraction <= 1
            or not math.isfinite(warm_overhead_nodes) or not warm_overhead_nodes.is_integer()
            or not 0 <= warm_overhead_nodes <= 8):
        raise ValueError("Forecast alpha must be 0.05–0.8; margin fractions 0–1; margin floor nonnegative; and minimum-active fraction 0–1.")
    default_work_factors = _workload_gpu_minutes_per_request()
    supplied_work_factors = payload.get("workload_gpu_minutes_per_request")
    if supplied_work_factors is not None and not isinstance(supplied_work_factors, dict):
        raise ValueError("Workload GPU-minutes/request must be an object keyed by request class.")
    work_factors = dict(default_work_factors)
    if supplied_work_factors is not None:
        for name, value in supplied_work_factors.items():
            if name not in CLASSES or isinstance(value, bool):
                raise ValueError("Workload factors must use known request classes and positive finite values.")
            try:
                factor = float(value)
            except (TypeError, ValueError):
                raise ValueError("Workload factors must use known request classes and positive finite values.") from None
            if not math.isfinite(factor) or factor <= 0:
                raise ValueError("Workload factors must use known request classes and positive finite values.")
            work_factors[name] = factor
    min_active_nodes = min(n, max(1, math.ceil(n * min_active_fraction)))
    if explicit_trace:
        requests = _validate_request_trace(payload.get("request_trace"), n * gpn)
    elif trace_source == "realistic":
        requests = generate_realistic_requests(seed, traffic_multiplier=traffic_multiplier,
                                               gpus_per_node=gpn, nodes=n)
    else:
        requests = generate_requests(seed, burst=bool(payload.get("bursts", True)),
                                     traffic_multiplier=traffic_multiplier)
    offered = _offered_gpu_trace(requests)
    flex_plan = _prepare_flexible_plan(n * gpn, payload.get("flexible_jobs"))
    # Forecast series are causal by construction: each bucket uses only prior
    # completed arrival counts; synthetic generator rates seed the first bucket.
    arrival_rates = _arrival_rate_forecasts(requests, alpha, generator_prior=not explicit_trace,
                                            generator_rate_multiplier=traffic_multiplier)
    policies = {}
    for name in ("always_on", "reactive", "forecast", "forecast_v2"):
        policies[name] = _run_policy(requests, offered, arrival_rates, work_factors, n, gpn, seed,
                                     alpha, margin_fraction, margin_floor_gpus, min_active_nodes,
                                     name, deepcopy(flex_plan),
                                     warm_overhead_nodes=int(warm_overhead_nodes),
                                     engine="v2" if name == "forecast_v2" else "legacy")
    baseline_plan = _greedy_asap_plan(flex_plan, n * gpn)
    baseline_run = _run_policy(requests, offered, arrival_rates, work_factors, n, gpn, seed,
                               alpha, margin_fraction, margin_floor_gpus, min_active_nodes,
                               "always_on", baseline_plan, queue_policy="fifo_next_fit",
                               warm_overhead_nodes=int(warm_overhead_nodes))
    baseline = {
        "label": "Always-on FIFO / ASAP (no energy scheduling)",
        "metrics": baseline_run["metrics"],
        "flexible_admission_status": baseline_run["flexible_admission_status"],
        "flexible_admission_reason": baseline_run["flexible_admission_reason"],
        "flexible_jobs": baseline_run["flexible_jobs"],
        "accepted_flexible_job_ids": [job["id"] for job in baseline_run["flexible_jobs"] if job.get("admitted")],
        "request_status_by_id": {item["id"]: item["status"] for item in baseline_run["replay"]["requests"]},
    }
    comparisons = {key: _compare_to_unscheduled_baseline(baseline, policy, key)
                   for key, policy in policies.items()}
    forecast_policy = policies["forecast_v2"]
    margin_sources = sorted({row["forecast_margin_source"] for row in forecast_policy["state_trace"]})
    realized_peak_minute = max(range(len(offered)), key=offered.__getitem__) if offered else 0
    realized_peak_frame = policies["forecast_v2"]["replay"]["frames"][realized_peak_minute]
    return {
        "seed": seed, "nodes": n, "base_nodes": n - headroom_nodes, "headroom_nodes": headroom_nodes,
        "headroom_description": f"Fixed inventory includes {headroom_nodes} added headroom nodes" if headroom_nodes else "Standard fixed inventory; no added headroom nodes",
        "gpus_per_node": gpn, "fleet_gpus": n * gpn,
        "traffic_profile": traffic_profile,
        "traffic_multiplier": None if explicit_trace else traffic_multiplier,
        "trace_source": "explicit" if explicit_trace else trace_source,
        "traffic_profile_description": ("Explicit request trace; preset multiplier is not applied" if explicit_trace
                                         else f"Synthetic generated arrivals at {traffic_multiplier:g}× normal rate ({traffic_profile} traffic); workload mix, durations, hardware and energy inputs unchanged"),
        "requests_generated": len(requests), "offered_peak_gpus": max(offered, default=0),
        "realized_peak_snapshot": {
            "minute": realized_peak_minute,
            "offered_gpus": offered[realized_peak_minute] if offered else 0,
            "active_nodes": realized_peak_frame["states"].count("active"),
            "warm_ready_nodes": realized_peak_frame["states"].count("warm"),
            "booting_nodes": realized_peak_frame["states"].count("booting"),
            "warming_nodes": realized_peak_frame["states"].count("warming"),
            "off_nodes": realized_peak_frame["states"].count("off"),
            "active_spare_gpus": realized_peak_frame["active_spare_gpus"],
            "formula_target_warm_nodes": realized_peak_frame["target_warm_nodes"],
            "warm_ready_deficit_nodes": realized_peak_frame["warm_ready_deficit_nodes"],
            "warm_stock_target_nodes": realized_peak_frame["warm_stock_target_nodes"],
            "warm_stock_shortfall_nodes": realized_peak_frame["warm_stock_shortfall_nodes"],
            "readiness_capacity_shortfall_gpus": realized_peak_frame["readiness_capacity_shortfall_gpus"],
        },
        "forecast_margin_rule": (f"95th percentile of matured prior window-maximum positive residuals after {MARGIN_HISTORY_WINDOWS_REQUIRED} windows; "
                                 f"otherwise max({margin_floor_gpus:g} GPUs, {margin_fraction:.0%} of predicted total demand)"),
        "selected_policy": "forecast_v2", "forecast_alpha": alpha, "margin_fraction": margin_fraction,
        "margin_floor_gpus": margin_floor_gpus,
        "minimum_active_nodes": min_active_nodes,
        "warm_overhead_nodes": int(warm_overhead_nodes),
        "flexible_schedule": {k: v for k, v in flex_plan.items() if k not in {"schedule", "jobs", "hourly_rates", "realtime_reservation_gpus"}}
        | {"scheduled_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"] if job.get("admitted")), 3),
           "candidate_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"]), 3)},
        "flexible_jobs": flex_plan["jobs"],
        "policies": policies,
        "unscheduled_baseline": baseline,
        "comparisons": comparisons,
        "assumptions": {
            "data_status": "synthetic_illustrative_not_measurements",
            "demand_model": ("heavy-tailed, over-dispersed, autocorrelated synthetic requests (log-normal sizes/durations, AR(1) intensity, diurnal class mix)" if trace_source == "realistic" and not explicit_trace
                             else "seeded Poisson requests; 5-minute arrivals; triangular service durations; optional hidden 3x bursts"),
            "trace_source": "explicit request_trace" if explicit_trace else trace_source,
            "forecast_v2_information_set": "ForecasterV2 receives arrivals seen, running jobs as (class, gpus, age), queued jobs as (class, gpus, arrival), own node states/ETAs, and its own accepted flexible commitments only. It never receives request durations, running end minutes, the LP hourly rate vector, the generator time-of-day curve, or future arrivals.",
            "forecast": (f"5-minute causal per-class arrival-rate EWMA (alpha={alpha:g}; requests/minute) convolved with the rounded duration survival distribution; "
                         f"initialized from {'the declared synthetic generator baseline' if payload.get('request_trace') is None else 'zero for the explicit request trace'} and adjusted by its known diurnal profile; separate expected future arrivals from exact running occupancy and a per-request queued-work placement plan"),
            "arrival_rate_initial_prior": "synthetic generator baseline; not observed history" if payload.get("request_trace") is None else "zero; explicit trace arrivals update future buckets causally",
            "forecast_workload_gpu_minutes_per_request": work_factors,
            "forecast_workload_factor_method": "Mean GPU count times the expected integer-minute duration after rounding a triangular(minimum, maximum, typical-mode) draw; generator factors are synthetic, not trace-fitted",
            "forecast_calibration_limit": (f"Matured positive demand residuals over the {COLD_TO_ACTIVE_MINUTES}-minute cold-start interval are accumulated causally within this synthetic run; after {MARGIN_HISTORY_WINDOWS_REQUIRED} complete windows the 95th percentile is used. "
                                            "No measured multi-day history or independent real-data calibration is supplied; before the threshold the manual fallback applies."),
            "forecast_margin_sources_seen": margin_sources,
            "forecast_margin_fallback": f"max({margin_floor_gpus:g} GPUs, {margin_fraction:.0%} of predicted total GPU demand); scenario assumption, not a calibrated confidence bound",
            "wait_aware_readiness_equation": f"Every five minutes, for each future minute h in [0,{FORECAST_HORIZON_MINUTES}], D_upper(h)=expected new-arrival GPU concurrency from the causal per-class EWMA and duration survival+known running GPUs until observed completion+queued jobs placed at earliest feasible non-preemptive slots+same-minute accepted flexible commitment+uncertainty margin; required whole-node capacity=ceil(D_upper(h)/GPUsPerNode). Existing active and boot pipelines count once. Warm-ready nodes are promoted immediately; for demand at least {COLD_TO_ACTIVE_MINUTES} minutes away, cold boot is started first to protect near-term warm stock. This is a causal greedy readiness plan, not a global optimizer.",
            "legacy_scalar_warm_target": "Diagnostic only: ceil(max(0, peak bridge demand including active spare subtraction)/GPUsPerNode). It no longer determines activation timing or the available warm overhead target.",
            "warm_overhead": f"Independent available warm-stock setting: {int(warm_overhead_nodes)} nodes (default {DEFAULT_WARM_OVERHEAD_NODES}, 0–8 configurable). Booting toward warm stock counts toward replenishment pipeline but is not ready. Requests may consume warm nodes; the controller starts replacement cold boots and reports temporary shortfall. Fleet overload can still exhaust reserve.",
            "warm_queue_fill_rule": "After real-time dispatch each minute, any requests still queued raise the warm-stock target to max(configured warm overhead, ceil(total queued request GPUs / GPUs per node)), capped at fleet size. OFF nodes begin a 20-minute boot toward warm stock; the target returns to the configured overhead when the queue clears. This treats all queued GPU demand as concurrent and can reserve more capacity than the queue will ultimately use.",
            "readiness_horizon_minutes": FORECAST_HORIZON_MINUTES,
            "warm_reserve_window_minutes": f"time-resolved horizon 0..{FORECAST_HORIZON_MINUTES} minutes; warm activation {WARM_START_MINUTES} minutes; full cold activation {COLD_TO_ACTIVE_MINUTES} minutes",
            "warm_queue_forecast_approximation": "Known queued requests are placed in controller-priority order at the earliest non-preemptive slot fitting projected active capacity after known running work, flexible commitments and expected new arrivals; jobs that cannot be placed in the horizon remain an explicit forecast limitation.",
            "minimum_active_floor": f"{min_active_nodes} active nodes ({min_active_fraction:.0%} of inventory), an explicit illustrative floor for short-latency service; not demand-derived",
            "node_control": "GPU allocation granularity; whole-node active/warm/boot/off states; no independent GPU power-gating assumed",
            "warm_start_minutes": WARM_START_MINUTES,
            "cold_to_warm_minutes": COLD_BOOT_TO_WARM_MINUTES,
            "cold_to_active_minutes": COLD_TO_ACTIVE_MINUTES,
            "forecast_margin_history_windows_required": MARGIN_HISTORY_WINDOWS_REQUIRED,
            "power_kw_it": {"active_node_idle": 1.0, "warm_node": 0.25, "boot_node": 1.2, "busy_gpu_increment": 0.35, "fixed_site_overhead": 18.0},
            "pue": 1.25,
            "renewables": "existing synthetic 24-hour kWh profile treated as average kW within each hour",
            "tariff": "Oct 2026 Fujian 1–10(20) kV State Grid agent-purchase single-part proxy; not this user's verified Xiamen tariff",
            "tariff_reference_url": "https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm",
            "grid_emissions": "0.55 kg CO2/kWh East-China annual-average proxy; not hourly marginal emissions or CO2e",
            "grid_emissions_reference_url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html",
            "flexible_jobs": "The hourly Pro-priority LP admits jobs and supplies a shared capacity-feasibility envelope for all policies. At runtime, accepted flexible work is lower priority than real-time requests and uses remaining active capacity in Pro-first, earliest-deadline order. Its remaining GPU-minutes are spread across remaining deadline minutes up to max_gpus, allowing safe waits and catch-up. Work left at deadline is explicitly unmet; no running real-time request is preempted.",
            "grid_cost_model": "Each simulated minute multiplies facility demand after PUE and same-hour renewable offset by the selected hour's illustrative Fujian time-of-use CNY/kWh rate. Hourly grid imports and cost are returned per controller. It is not a customer bill and excludes contract-specific capacity/demand charges.",
        },
    }


def _greedy_asap_plan(accepted_plan: dict[str, Any], fleet_gpus: int) -> dict[str, Any]:
    """Create an arrival-order, earliest-available flexible schedule for baseline diagnostics."""
    plan = deepcopy(accepted_plan)
    jobs = plan["jobs"]
    rates = [[0.0] * 24 for _ in jobs]
    if plan["admission_status"] == "admitted":
        remaining = [max(0.0, float(job["gpu_hours"])) for job in jobs]
        order = sorted(range(len(jobs)), key=lambda i: (jobs[i]["arrival"], i))
        for hour in range(24):
            available = float(fleet_gpus)
            for ji in order:
                job = jobs[ji]
                if not job.get("admitted") or not job["arrival"] <= hour < job["deadline"]:
                    continue
                allocation = min(float(job["max_gpus"]), remaining[ji], available)
                if allocation > 1e-9:
                    rates[ji][hour] = allocation
                    remaining[ji] -= allocation
                    available -= allocation
    plan["schedule"] = rates
    plan["hourly_rates"] = rates
    return plan


def _percentage_saving(baseline_value: float | None, optimized_value: float | None) -> float | None:
    if baseline_value is None or optimized_value is None or abs(float(baseline_value)) <= 1e-12:
        return None
    return round((float(baseline_value) - float(optimized_value)) / float(baseline_value) * 100, 3)


def _compare_to_unscheduled_baseline(baseline: dict[str, Any], optimized: dict[str, Any],
                                     policy_key: str) -> dict[str, Any]:
    baseline_metrics = baseline["metrics"]
    optimized_metrics = optimized["metrics"]
    base_status = baseline.get("request_status_by_id", {})
    optimized_status = {item["id"]: item["status"] for item in optimized.get("replay", {}).get("requests", [])}
    same_request_outcomes = base_status == optimized_status
    base_jobs = {job["id"]: job for job in baseline.get("flexible_jobs", [])}
    optimized_jobs = {job["id"]: job for job in optimized.get("flexible_jobs", [])}
    same_flex_outcomes = set(base_jobs) == set(optimized_jobs)
    if same_flex_outcomes:
        for job_id in base_jobs:
            b, o = base_jobs[job_id], optimized_jobs[job_id]
            if bool(b.get("admitted")) != bool(o.get("admitted")):
                same_flex_outcomes = False
                break
            if abs(float(b.get("delivered_gpu_hours", 0)) - float(o.get("delivered_gpu_hours", 0))) > 1e-6:
                same_flex_outcomes = False
                break
            if bool(b.get("deadline_met")) != bool(o.get("deadline_met")):
                same_flex_outcomes = False
                break
    service_comparable = same_request_outcomes and same_flex_outcomes
    service_note = (
        "Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; "
        "wait/completion-latency differences remain reported separately."
        if service_comparable else
        "Service outcomes differ: compare completion, rejection/backlog, latency, flexible delivered work, and deadlines before interpreting energy or cost changes."
    )
    savings_fields = {
        "electricity_pct": "facility_kwh",
        "cost_pct": "cost_cny",
        "emissions_pct": "emissions_kg",
        "grid_import_pct": "grid_kwh",
    }
    savings = {name: _percentage_saving(baseline_metrics.get(metric), optimized_metrics.get(metric))
               for name, metric in savings_fields.items()}
    savings_reason = {}
    for name, metric in savings_fields.items():
        base_value, optimized_value = baseline_metrics.get(metric), optimized_metrics.get(metric)
        if base_value is None or optimized_value is None:
            savings_reason[name] = f"{metric} is unavailable for baseline or selected controller; percentage undefined."
        elif abs(float(base_value)) <= 1e-12:
            savings_reason[name] = f"Baseline {metric} is zero; percentage undefined."
        else:
            savings_reason[name] = None
    return {
        "baseline": {"key": "unscheduled", "label": baseline["label"], "metrics": baseline_metrics},
        "optimized": {"key": policy_key, "label": optimized["label"], "metrics": optimized_metrics},
        "savings": savings,
        "savings_reason": savings_reason,
        "service_comparable": service_comparable,
        "service_note": service_note,
    }


def _prepare_flexible_plan(fleet_gpus: int, custom_jobs: Any = None) -> dict[str, Any]:
    """Use the existing LP to admit and schedule flexible work once for all policies."""
    if custom_jobs is not None:
        if not isinstance(custom_jobs, list):
            raise ValueError("Flexible jobs must be a list.")
        candidate_override = [dict(job) if isinstance(job, dict) else job for job in custom_jobs]
        if not all(isinstance(job, dict) for job in candidate_override):
            raise ValueError("Each flexible job must be an object.")
        _validate_custom_jobs(candidate_override)
    else:
        candidate_override = None
    try:
        case = build_case({"gpu_count": fleet_gpus})
    except ValueError as error:
        candidate_jobs = [dict(job) for job in (candidate_override if candidate_override is not None else JOBS)]
        return {"admission_status": "infeasible", "admission_reason": str(error),
                "priority_policy": "pro_priority", "schedule": [], "jobs": [
                    {**job, "admitted": False, "status": "not_admitted", "delivered_gpu_hours": 0.0,
                     "unmet_gpu_hours": job["gpu_hours"], "deadline_met": False}
                    for job in candidate_jobs
                ], "hourly_rates": [[0.0] * 24 for _ in candidate_jobs], "realtime_reservation_gpus": [0.0] * 24}
    if candidate_override is not None:
        case["jobs"] = candidate_override
    candidate_jobs = [dict(job) for job in case["jobs"]]
    _validate_custom_jobs(candidate_jobs)
    case["jobs"] = candidate_jobs
    validate_case(case)
    result = solve_lp(case, "pro_priority")
    if not result.get("success"):
        return {"admission_status": "infeasible", "admission_reason": result.get("status", "LP infeasible"),
                "priority_policy": "pro_priority", "schedule": [], "jobs": [
                    {**job, "admitted": False, "status": "not_admitted", "delivered_gpu_hours": 0.0,
                     "unmet_gpu_hours": job["gpu_hours"], "deadline_met": False}
                    for job in candidate_jobs
                ], "hourly_rates": [[0.0] * 24 for _ in candidate_jobs], "realtime_reservation_gpus": case["realtime_gpus"]}
    schedule = result["schedule_gpu_hours"]
    rates = [[max(0.0, float(value)) for value in row] for row in schedule]
    return {"admission_status": "admitted", "admission_reason": None, "priority_policy": "pro_priority",
            "schedule": rates, "jobs": [{**job, "admitted": True, "status": "scheduled",
                                             "delivered_gpu_hours": 0.0, "unmet_gpu_hours": job["gpu_hours"],
                                             "deadline_met": False} for job in candidate_jobs],
            "hourly_rates": rates, "realtime_reservation_gpus": case["realtime_gpus"]}


def _validate_custom_jobs(jobs: list[dict[str, Any]]) -> None:
    if len(jobs) > 64:
        raise ValueError("At most 64 flexible jobs are supported per dynamic simulation.")
    ids = set()
    for job in jobs:
        try:
            arrival, deadline = job["arrival"], job["deadline"]
            gpu_hours, max_gpus = float(job["gpu_hours"]), job["max_gpus"]
            tier, job_id = job.get("tier", "standard"), job["id"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each flexible job needs id, arrival, deadline, GPU-hours, and maximum GPUs.") from None
        if (isinstance(arrival, bool) or not isinstance(arrival, int)
                or isinstance(deadline, bool) or not isinstance(deadline, int)
                or not 0 <= arrival < deadline <= 24
                or isinstance(max_gpus, bool) or not isinstance(max_gpus, int) or max_gpus < 0
                or not math.isfinite(gpu_hours) or gpu_hours < 0
                or tier not in {"pro", "standard"} or not isinstance(job_id, str)
                or not job_id or job_id in ids):
            raise ValueError("Flexible jobs need unique IDs, 0 ≤ arrival < deadline ≤ 24, nonnegative GPU-hours/max GPUs, and Pro/Standard tier.")
        job.setdefault("name", job_id)
        job.setdefault("tier", tier)
        ids.add(job_id)


def _validate_request_trace(raw: Any, fleet_gpus: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 10000:
        raise ValueError("Request trace must be a list containing at most 10,000 requests.")
    result = []
    seen = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("Each request trace item must be an object.")
        rid = str(item.get("id", f"trace-{index}"))
        kind = item.get("class", "interactive")
        try:
            values = [item["arrival"], item["gpus"], item["duration"], item.get("latency", 2 if kind == "interactive" else 30)]
            if any(isinstance(value, bool) or not float(value).is_integer() for value in values):
                raise ValueError
            arrival, gpus, duration, latency = (int(value) for value in values)
        except (KeyError, TypeError, ValueError):
            raise ValueError("Requests need whole-number arrival, GPU, duration and latency values.") from None
        if (rid in seen or kind not in CLASSES or not 0 <= arrival < MINUTES_PER_DAY
                or not 1 <= gpus <= fleet_gpus or not 1 <= duration <= MINUTES_PER_DAY
                or not 0 <= latency <= MINUTES_PER_DAY):
            raise ValueError("Request trace contains duplicate IDs or values outside the supported range.")
        seen.add(rid)
        result.append({"id": rid, "class": kind, "arrival": arrival, "gpus": gpus,
                       "duration": duration, "latency": latency})
    return sorted(result, key=lambda r: (r["arrival"], r["id"]))


def _run_policy(requests, offered, arrival_rates, work_factors, n, gpn, seed, alpha,
                margin_fraction, margin_floor_gpus, min_active_nodes, policy, flex_plan,
                *, queue_policy="interactive_batch", warm_overhead_nodes=DEFAULT_WARM_OVERHEAD_NODES,
                engine="legacy"):
    first_hour_flex = sum(row[0] for row in flex_plan["hourly_rates"])
    first_hour_reservation = flex_plan["realtime_reservation_gpus"][0]
    first_hour_nodes = math.ceil((first_hour_flex + first_hour_reservation) / gpn)
    initial_active = n if policy == "always_on" else min(n, max(2, n // 2, first_hour_nodes))
    initial_warm = min(max(0, warm_overhead_nodes), max(0, n - initial_active))
    nodes = [Node("active" if i < initial_active else "warm" if i < initial_active + initial_warm else "off") for i in range(n)]
    forecaster = (ForecasterV2(gpn, n, WARM_START_MINUTES, COLD_TO_ACTIVE_MINUTES)
                  if engine == "v2" else None)
    # bounded initial queue / state tracking; generated offered load is not dropped
    arrived_at: dict[int, list[dict[str, Any]]] = {}
    for r in requests:
        arrived_at.setdefault(r["arrival"], []).append(r)
    statuses = {r["id"]: {**r, "status": "upcoming"} for r in requests}
    waiting: deque[str] = deque()
    running: dict[str, dict[str, Any]] = {}
    timeline_states, hist_wait, hist_energy, replay_frames = [], [], [], []
    # time-weighted accounting at one-minute resolution
    totals = {k: 0.0 for k in ("facility_kwh", "grid_kwh", "renewable_used_kwh", "renewable_curtailed_kwh", "cost_cny", "emissions_kg")}
    hourly_grid_costs = [{"hour": hour, "rate_cny_kwh": TOU_PRICE_CNY[hour],
                          "tariff_period": "valley" if hour < 8 else "peak" if hour in (10, 11, 15, 16, 17, 18, 19, 20, 21) else "flat",
                          "grid_kwh": 0.0, "renewable_used_kwh": 0.0,
                          "facility_kwh": 0.0, "emissions_kg": 0.0, "cost_cny": 0.0}
                         for hour in range(24)]
    served_gpu_minutes = 0
    energy_accounted_gpu_minutes = 0.0
    flexible_gpu_minutes_missed = 0.0
    flexible_hour_delivered = [[0.0] * 24 for _ in flex_plan["jobs"]]
    flex_done_by_job = [0.0] * len(flex_plan["jobs"])
    flex_minute_allocations: list[tuple[int, float]] = []
    margin_window_errors: list[float] = []
    v2_margins: list[float] = []
    forecast_debug: list[dict[str, Any]] = []
    issued_window_forecasts: dict[int, dict[int, float]] = {}
    forecast = upper = forecast_realtime = forecast_running = forecast_queue = forecast_flex = 0.0
    forecast_window_peak = 0.0
    margin = margin_floor_gpus
    margin_source = "manual_assumption_fallback"
    target_warm = target_warm_fleet_shortfall = target_warm_realizable = 0
    warm_stock_target = warm_stock_shortfall = warm_ready_deficit = 0
    queued_reserve_demand_nodes = 0
    forecast_target_active = forecast_warm_started = forecast_cold_started = 0
    readiness_shortfall = pre_warm_shortfall = peak_fleet_shortfall = 0.0
    readiness_shortfall_minutes = 0
    reserve_pipeline_gap = 0
    for minute in range(MINUTES_PER_DAY):
        flex_minute_allocations = []
        _advance_transitions(nodes)
        # completed work releases GPU slots
        for rid, job in list(running.items()):
            if job["end"] <= minute:
                for ni, used in job["nodes"]:
                    nodes[ni].used -= used
                statuses[rid].update(status="completed", completed_minute=minute,
                                     wait_minutes=statuses[rid]["start"] - statuses[rid]["arrival"],
                                     response_minutes=minute - statuses[rid]["arrival"])
                hist_wait.append(statuses[rid]["wait_minutes"])
                if forecaster is not None:
                    forecaster.observe_completion_for(statuses[rid]["class"],
                                                      minute - statuses[rid]["start"])
                del running[rid]
        # Finish jobs whose declared deadline is at this boundary; any planned
        # work that could not run before it is an explicit miss, never silently
        # rescheduled past the deadline.
        for ji, job in enumerate(flex_plan["jobs"]):
            if job.get("admitted") and job["deadline"] * 60 == minute:
                remaining = max(0.0, job["gpu_hours"] * 60 - flex_done_by_job[ji])
                flexible_gpu_minutes_missed += remaining
                job.update(status="completed" if remaining <= 1e-6 else "deadline_missed",
                           delivered_gpu_hours=flex_done_by_job[ji] / 60,
                           unmet_gpu_hours=remaining / 60, deadline_met=remaining <= 1e-6)

        # Arrivals at this minute are now observable and are included once in
        # the known queue; the forecast never reads not-yet-arrived requests.
        for r in arrived_at.get(minute, []):
            if r["gpus"] > n * gpn:
                statuses[r["id"]].update(status="rejected", reason="Request exceeds installed fleet", rejected_minute=minute)
            elif len(waiting) >= 256:
                statuses[r["id"]].update(status="rejected", reason="Queue reached the 256-request scenario limit", rejected_minute=minute)
            else:
                statuses[r["id"]]["status"] = "queued"
                waiting.append(r["id"])
                if forecaster is not None:
                    forecaster.observe_arrival(minute, r["class"], r["gpus"])

        # Mature only issued forecasts whose entire requested minute has now
        # been observed. Residuals use offered demand at this minute, not future
        # trace values exposed before their timestamp.
        if policy in FORECAST_POLICIES:
            actual_total = offered[minute] + _flex_rate_at(flex_plan["hourly_rates"], minute)
            for issue_minute, predictions in list(issued_window_forecasts.items()):
                if minute in predictions:
                    predictions[minute] = max(0.0, actual_total - predictions[minute])
                if minute == issue_minute + COLD_TO_ACTIVE_MINUTES:
                    margin_window_errors.append(max(predictions.values(), default=0.0))
                    del issued_window_forecasts[issue_minute]

        # Causal reserve update every five minutes. The adopted target window
        # is [warm-to-active, fully-off-to-active), with total demand evaluated
        # minute-by-minute so flexible commitments are paired at the same time.
        if forecaster is not None:
            arrivals_now: dict[str, int] = {}
            for observed_request in arrived_at.get(minute, []):
                arrivals_now[observed_request["class"]] = arrivals_now.get(observed_request["class"], 0) + 1
            forecaster.observe_minute(minute, arrivals_now)

        if minute % BUCKET == 0:
            horizon = FORECAST_HORIZON_MINUTES
            if engine == "v2":
                (predicted_by_offset, upper_by_offset, realtime_by_offset, running_by_offset,
                 queue_by_offset, flex_by_offset, margin, margin_source,
                 queue_unplaced, v2_margins) = _forecast_v2_curve(
                    forecaster, minute, running, waiting, statuses, nodes, flex_plan,
                    flex_done_by_job, gpn, horizon)
            else:
              rates = arrival_rates[min(minute // BUCKET, len(arrival_rates) - 1)]
              future_arrivals = _expected_future_arrival_concurrency(rates, minute, horizon, work_factors)
              queue_profile, queue_starts, queue_unplaced = _queued_workload_profile(
                  waiting, statuses, running, nodes, minute, horizon, gpn, flex_plan,
                  future_arrivals, queue_policy,
              )
              predicted_by_offset: dict[int, float] = {}
              realtime_by_offset: dict[int, float] = {}
              running_by_offset: dict[int, float] = {}
              queue_by_offset: dict[int, float] = {}
              flex_by_offset: dict[int, float] = {}
              for offset in range(horizon + 1):
                  future_minute = minute + offset
                  future_flex = _flex_rate_at(flex_plan["hourly_rates"], future_minute)
                  future_running = _known_running_gpu_demand(running, future_minute)
                  future_queue = queue_profile[offset]
                  new_arrivals = future_arrivals[offset]
                  realtime = new_arrivals + future_running + future_queue
                  predicted_by_offset[offset] = realtime + future_flex
                  realtime_by_offset[offset] = new_arrivals
                  running_by_offset[offset] = future_running
                  queue_by_offset[offset] = future_queue
                  flex_by_offset[offset] = future_flex

            bridge_offsets = list(range(1, horizon + 1))
            forecast_total_peak = max((predicted_by_offset[offset] for offset in bridge_offsets), default=0.0)
            forecast_peak_offset = max(bridge_offsets, key=lambda offset: predicted_by_offset[offset], default=1)
            forecast_window_peak = forecast_total_peak
            if engine != "v2":
                margin, margin_source = _forecast_margin(margin_window_errors, forecast_total_peak,
                                                         margin_fraction, margin_floor_gpus)
                upper_by_offset = [predicted_by_offset[offset] + margin for offset in range(horizon + 1)]
            upper = predicted_by_offset[0] + margin
            forecast = realtime_by_offset[0]
            forecast_realtime = realtime_by_offset[0]
            forecast_running = running_by_offset[0]
            forecast_queue = queue_by_offset[0]
            forecast_flex = flex_by_offset[0]
            forecast_debug.append({
                "minute": minute,
                "engine": engine,
                "predicted": [round(float(predicted_by_offset[o]), 3) for o in range(horizon + 1)],
                "upper": [round(float(upper_by_offset[o]), 3) for o in range(horizon + 1)],
                "margin_gpus": round(float(margin), 3),
                "margin_source": margin_source,
                "margins_by_bucket": [round(float(v), 2) for v in v2_margins] if engine == "v2" else [],
            })
            if policy in FORECAST_POLICIES:
                active_nodes = sum(x.state == "active" for x in nodes)
                # Keep the earlier static target as a diagnostic; actual
                # activation decisions now follow a time-resolved readiness plan.
                legacy_reserve = _warm_target([predicted_by_offset[offset] + margin for offset in range(
                    WARM_START_MINUTES, COLD_TO_ACTIVE_MINUTES)],
                                       active_nodes, n, gpn)
                target_warm = legacy_reserve["target_warm_nodes"]
                target_warm_fleet_shortfall = legacy_reserve["target_warm_fleet_shortfall_nodes"]
                target_warm_realizable = legacy_reserve["target_warm_realizable_nodes"]
                peak_fleet_shortfall = max((max(0.0, demand - n * gpn) for demand in upper_by_offset), default=0.0)
                readiness_plan = _plan_active_readiness(nodes, upper_by_offset, gpn)
                readiness_shortfall = readiness_plan["peak_readiness_gap_gpus"]
                readiness_shortfall_minutes = readiness_plan["readiness_gap_minutes"]
                pre_warm_shortfall = readiness_plan["pre_warm_active_gap_gpus"]
                forecast_target_active = readiness_plan["peak_target_active_nodes"]
                forecast_warm_started = readiness_plan["warm_nodes_started"]
                forecast_cold_started = readiness_plan["cold_nodes_started"]
                # Ready warm overhead is an independent operating reserve. Nodes
                # consumed by the activation planner have already left that pool.
                warm_stock_target = warm_overhead_nodes
                _ensure_warm_reserve(nodes, warm_stock_target)
                # Mature only errors in the cold-start interval; later
                # unobserved horizon values are not residual measurements.
                predicted_by_minute = {
                    minute + offset: predicted_by_offset[offset]
                    for offset in range(1, COLD_TO_ACTIVE_MINUTES + 1)
                    if minute + offset < MINUTES_PER_DAY
                }
                issued_window_forecasts[minute] = predicted_by_minute
                reserve_pipeline = _warm_stock_pipeline_nodes(nodes)
                reserve_pipeline_gap = max(0, warm_stock_target - reserve_pipeline)
                warm_ready_deficit = max(0, warm_stock_target - sum(x.state == "warm" for x in nodes))
                stock_possible_nodes = sum(
                    x.state in ("warm", "off") or (x.state == "booting" and x.purpose == "warm_stock")
                    for x in nodes
                )
                warm_stock_shortfall = max(0, warm_stock_target - stock_possible_nodes)
            else:
                target_warm = target_warm_fleet_shortfall = target_warm_realizable = 0
                warm_stock_target = warm_stock_shortfall = warm_ready_deficit = 0
                readiness_shortfall = pre_warm_shortfall = peak_fleet_shortfall = 0.0
                readiness_shortfall_minutes = reserve_pipeline_gap = 0
                forecast_target_active = forecast_warm_started = forecast_cold_started = 0
        planned_flex = _flex_rate_at(flex_plan["hourly_rates"], minute)
        # Only reactive control scales directly from fixed flexible rates.
        # Forecast control keeps flexible work behind arriving requests and
        # lets its readiness planner start cold capacity ahead of deadlines.
        if policy != "always_on":
            if policy == "reactive":
                known_peak = _required_capacity_peak(flex_plan, minute, COLD_TO_ACTIVE_MINUTES)
                known_target = min(n, math.ceil(known_peak / gpn))
                _scale_up(nodes, max(known_target, math.ceil(planned_flex / gpn)), gpn)
        # Arrivals remain preserved in the queue; over-capacity requests above
        # are explicitly rejected rather than disappearing from offered load.
        if policy != "always_on" and waiting:
            protected_flex = planned_flex if policy == "reactive" else 0.0
            required = math.ceil((protected_flex + sum(r["gpus"] for r in running.values()) + sum(statuses[r]["gpus"] for r in waiting)) / gpn)
            _scale_up(nodes, min(n, required), gpn)
        if policy in FORECAST_POLICIES:
            # Reactive same-minute commitments can consume planned standby
            # while demand is being dispatched; restore the configured stock
            # from the off fleet if it remains available.
            _ensure_warm_reserve(nodes, warm_overhead_nodes)
        # Real-time requests take the first dispatch opportunity. Warm nodes
        # are immediately promotable in this model when active spare is short.
        flex_busy_gpu = 0.0
        # Serve interactive before batch; 15-minute aging protects batch starts.
        while waiting:
            free = [(ni, gpn - node.used) for ni, node in enumerate(nodes) if node.state == "active"]
            free_gpu = sum(x for _, x in free)
            dispatchable_gpu = free_gpu + sum(gpn - node.used for node in nodes if node.state == "warm")
            if not dispatchable_gpu:
                break
            rid = _choose_waiting_request(waiting, statuses, minute, dispatchable_gpu,
                # Accepted flexible work may slip within its window; RT work
                # must not be held back for a synthetic average-rate slot.
                admissible=lambda _candidate: True,
                queue_policy=queue_policy)
            if rid is None:
                break
            waiting.remove(rid)
            req = statuses[rid]
            needed_after_active = max(0, req["gpus"] - free_gpu)
            if needed_after_active:
                for node in nodes:
                    if node.state == "warm" and needed_after_active > 0:
                        node.state, node.remaining, node.purpose = "active", 0, None
                        node.idle = 0
                        needed_after_active -= gpn
                free = [(ni, gpn - node.used) for ni, node in enumerate(nodes) if node.state == "active"]
            need, alloc = req["gpus"], []
            for ni, available in free:
                take = min(need, available)
                if take:
                    nodes[ni].used += take
                    alloc.append((ni, take))
                    need -= take
                if not need:
                    break
            req.update(status="running", start=minute)
            running[rid] = {"end": minute + req["duration"], "nodes": alloc, "gpus": req["gpus"]}
        if policy in FORECAST_POLICIES:
            # If real-time work still cannot start, expand warm stock to cover
            # its queued GPU total (up to fleet size). Booting toward this
            # target makes the readiness gap visible instead of leaving nodes
            # powered off while the queue waits.
            queued_reserve_demand_nodes = _queued_reserve_demand_nodes(waiting, statuses, gpn, n)
            warm_stock_target = max(warm_overhead_nodes, queued_reserve_demand_nodes)
            _ensure_warm_reserve(nodes, warm_stock_target)
            stock_possible_nodes = sum(
                node.state in ("warm", "off") or (node.state == "booting" and node.purpose == "warm_stock")
                for node in nodes
            )
            warm_stock_shortfall = max(0, warm_stock_target - stock_possible_nodes)
            warm_ready_deficit = max(0, warm_stock_target - sum(node.state == "warm" for node in nodes))
            reserve_pipeline_gap = max(0, warm_stock_target - _warm_stock_pipeline_nodes(nodes))
        # Accepted flexible jobs use capacity left after real-time dispatch,
        # in Pro-first/earliest-deadline order. They can catch up anywhere in
        # their window up to their declared parallelism cap.
        if flex_plan["admission_status"] == "admitted":
            flex_order = sorted(range(len(flex_plan["jobs"])), key=lambda ji: (
                0 if flex_plan["jobs"][ji].get("tier") == "pro" else 1,
                flex_plan["jobs"][ji]["deadline"], flex_plan["jobs"][ji]["arrival"], ji,
            ))
            for ji in flex_order:
                job = flex_plan["jobs"][ji]
                if not job.get("admitted") or not job["arrival"] * 60 <= minute < job["deadline"] * 60:
                    continue
                remaining_work = max(0.0, job["gpu_hours"] * 60 - flex_done_by_job[ji])
                desired = min(float(job["max_gpus"]), remaining_work)
                allocated, alloc_nodes = _allocate_active(nodes, desired, gpn)
                flex_busy_gpu += allocated
                flex_done_by_job[ji] += allocated
                flexible_hour_delivered[ji][minute // 60] += allocated
                flex_minute_allocations.extend(alloc_nodes)
        # Hysteretic scale-down; no occupied active nodes can sleep. Warm
        # capacity is powered off only when it exceeds the current target.
        if policy != "always_on":
            active_demand = planned_flex + sum(r["gpus"] for r in running.values()) + sum(statuses[r]["gpus"] for r in waiting)
            known_peak = _required_capacity_peak(flex_plan, minute, 25)
            minimum_active = max(min_active_nodes, math.ceil(active_demand / gpn), math.ceil(known_peak / gpn))
            active_ids = [i for i, node in enumerate(nodes) if node.state == "active"]
            for ni in reversed(active_ids):
                node = nodes[ni]
                node.idle = node.idle + 1 if node.used == 0 else 0
                if len([x for x in nodes if x.state == "active"]) > minimum_active and node.idle >= 30:
                    node.state = "warm"
                    node.idle = 0
            warm_ids = [i for i, node in enumerate(nodes) if node.state == "warm"]
            desired_warm = warm_stock_target if policy in FORECAST_POLICIES else 0
            for ni in reversed(warm_ids):
                node = nodes[ni]
                node.idle += 1
                if len([x for x in nodes if x.state == "warm"]) > desired_warm and node.idle >= 30:
                    node.state = "off"
                    node.idle = 0
            # Forecast controller replenishes its warm target at the next
            # bucket; reactive control intentionally keeps no forecast reserve.
        if forecaster is not None:
            # Observed demand pressure = real-time work plus flexible work the
            # controller has actually allocated this minute. This is exactly what
            # the forecaster is asked to predict, so residuals are comparable.
            queued_gpus_now = sum(statuses[rid]["gpus"] for rid in waiting)
            observed_demand_now = (sum(job["gpus"] for job in running.values())
                                   + queued_gpus_now + flex_busy_gpu)
            forecaster.score(minute, observed_demand_now)

        # Hourly supply curves are rates/energy per one-hour slot converted to a per-minute quantity.
        active = sum(x.state == "active" for x in nodes)
        warm = sum(x.state == "warm" for x in nodes)
        boot = sum(x.state in ("booting", "warming") for x in nodes)
        busy_gpus = sum(r["gpus"] for r in running.values())
        served_gpu_minutes += busy_gpus
        total_busy_gpus = busy_gpus + flex_busy_gpu
        energy_accounted_gpu_minutes += total_busy_gpus
        it_kw = 18.0 + active * 1.0 + warm * 0.25 + boot * 1.2 + total_busy_gpus * 0.35
        facility = it_kw * 1.25 / 60
        hour = minute // 60
        renewable_available = RENEWABLE_AVAILABLE[hour] / 60
        used = min(facility, renewable_available)
        grid = facility - used
        totals["facility_kwh"] += facility
        totals["grid_kwh"] += grid
        totals["renewable_used_kwh"] += used
        totals["renewable_curtailed_kwh"] += renewable_available - used
        totals["cost_cny"] += grid * TOU_PRICE_CNY[hour]
        emissions = grid * GRID_CO2_KG_KWH
        hourly_grid_costs[hour]["grid_kwh"] += grid
        hourly_grid_costs[hour]["renewable_used_kwh"] += used
        hourly_grid_costs[hour]["facility_kwh"] += facility
        hourly_grid_costs[hour]["emissions_kg"] += emissions
        hourly_grid_costs[hour]["cost_cny"] += grid * TOU_PRICE_CNY[hour]
        totals["emissions_kg"] += emissions
        # Preserve an actual one-minute playback frame. Per-node power is IT
        # draw before shared site overhead/PUE; facility_kw includes both.
        node_power = [
            (1.0 if node.state == "active" else 0.25 if node.state == "warm" else 1.2 if node.state in ("warming", "booting") else 0.0)
            + 0.35 * node.used
            for node in nodes
        ]
        realtime_used_by_node = [0.0] * n
        flexible_used_by_node = [0.0] * n
        for job in running.values():
            for ni, allocated in job["nodes"]:
                realtime_used_by_node[ni] += allocated
        for ni, allocated in flex_minute_allocations:
            flexible_used_by_node[ni] += allocated
        replay_frames.append({
            "minute": minute,
            "states": [node.state for node in nodes],
            "used_gpus": [round(float(node.used), 3) for node in nodes],
            "realtime_used_gpus": [round(value, 3) for value in realtime_used_by_node],
            "flexible_used_gpus": [round(value, 3) for value in flexible_used_by_node],
            "power_kw": [round(value, 4) for value in node_power],
            # Keep the reserve decision inspectable at the same one-minute
            # resolution as the node replay. Warm target is a desired count;
            # only the explicit node states describe readiness.
            "active_capacity_gpus": active * gpn,
            "active_spare_gpus": round(max(0.0, active * gpn - busy_gpus - flex_busy_gpu), 3),
            "warm_ready_capacity_gpus": warm * gpn,
            "dispatchable_capacity_gpus": round(max(0.0, active * gpn - busy_gpus - flex_busy_gpu) + warm * gpn, 3),
            "target_warm_nodes": target_warm if policy in FORECAST_POLICIES else None,
            "forecast_target_active_nodes": forecast_target_active if policy in FORECAST_POLICIES else None,
            "forecast_warm_nodes_started": forecast_warm_started if policy in FORECAST_POLICIES else 0,
            "forecast_cold_nodes_started": forecast_cold_started if policy in FORECAST_POLICIES else 0,
            "warm_stock_target_nodes": warm_stock_target if policy in FORECAST_POLICIES else None,
            "warm_overhead_nodes": warm_overhead_nodes if policy in FORECAST_POLICIES else 0,
            "queued_reserve_demand_nodes": queued_reserve_demand_nodes if policy in FORECAST_POLICIES else 0,
            "warm_stock_shortfall_nodes": warm_stock_shortfall if policy in FORECAST_POLICIES else 0,
            "warm_ready_deficit_nodes": max(0, warm_stock_target - sum(node.state == "warm" for node in nodes)) if policy in FORECAST_POLICIES else 0,
            "warm_stock_shortfall_reason": (
                "Insufficient inactive fleet capacity to reach the warm-stock target" if policy in FORECAST_POLICIES and warm_stock_shortfall > 0
                else "Cold capacity is still booting or warming" if policy in FORECAST_POLICIES and warm_stock_target > sum(node.state == "warm" for node in nodes) and sum(node.state in ("warming", "booting") for node in nodes) > 0
                else "Warm stock is currently being consumed for workload" if policy in FORECAST_POLICIES and warm_stock_target > 0 and sum(node.state == "warm" for node in nodes) < warm_stock_target
                else ""
            ),
            "target_warm_fleet_shortfall_nodes": target_warm_fleet_shortfall if policy in FORECAST_POLICIES else 0,
            "warm_reserve_ready_nodes": sum(node.state == "warm" for node in nodes),
            "warm_reserve_booting_nodes": sum(node.state == "booting" and node.purpose == "warm_stock" for node in nodes),
            "warm_reserve_warming_nodes": sum(node.state == "warming" for node in nodes),
            "warm_reserve_pipeline_nodes": _warm_stock_pipeline_nodes(nodes),
            "warm_reserve_pipeline_gap_nodes": max(
                0, warm_stock_target - _warm_stock_pipeline_nodes(nodes)
            ) if policy in FORECAST_POLICIES else 0,
            "readiness_capacity_shortfall_gpus": round(readiness_shortfall, 2) if policy in FORECAST_POLICIES else 0.0,
            "pre_warm_active_shortfall_gpus": round(pre_warm_shortfall, 2) if policy in FORECAST_POLICIES else 0.0,
            "forecast_capacity_shortfall_gpus": round(peak_fleet_shortfall, 2) if policy in FORECAST_POLICIES else 0.0,
            "forecast_margin_gpus": round(margin, 2) if policy in FORECAST_POLICIES else 0.0,
            "forecast_margin_source": margin_source if policy in FORECAST_POLICIES else None,
            "forecast_window_peak_upper_gpus": round(forecast_window_peak + margin, 2) if policy in FORECAST_POLICIES else 0.0,
            "facility_kw": round(it_kw * 1.25, 4),
            "grid_kwh": round(grid, 6),
            "renewable_used_kwh": round(used, 6),
            "cumulative_cost_cny": round(totals["cost_cny"], 6),
            "cumulative_grid_kwh": round(totals["grid_kwh"], 6),
            "cumulative_emissions_kg": round(totals["emissions_kg"], 6),
        })
        if minute % 5 == 0:
            active_now = sum(x.state == "active" for x in nodes)
            warm_now = sum(x.state == "warm" for x in nodes)
            booting_now = sum(x.state == "booting" for x in nodes)
            warming_now = sum(x.state == "warming" for x in nodes)
            pipeline_nodes = _warm_stock_pipeline_nodes(nodes)
            reserve_pipeline_gap = max(0, warm_stock_target - pipeline_nodes) if policy in FORECAST_POLICIES else 0
            total_upper = forecast_window_peak + margin
            shortfall = peak_fleet_shortfall if policy in FORECAST_POLICIES else 0.0
            timeline_states.append({"minute": minute, "offered_gpus": offered[minute],
                                    "forecast_gpus": round(forecast, 2),
                                    "forecast_realtime_gpu_demand": round(forecast_realtime, 2),
                                    "forecast_running_gpu_demand": round(forecast_running, 2),
                                    "forecast_queued_gpu_pressure": round(forecast_queue, 2),
                                    "forecast_upper_gpus": round(upper, 2),
                                    "flexible_commitment_gpus": round(forecast_flex, 2),
                                    "forecast_total_upper_gpus": round(total_upper, 2),
                                    "forecast_window_peak_minute": minute + forecast_peak_offset,
                                    "forecast_window_peak_realtime_gpus": round(
                                        predicted_by_offset[forecast_peak_offset] - flex_by_offset[forecast_peak_offset], 2),
                                    "forecast_window_peak_flexible_gpus": round(flex_by_offset[forecast_peak_offset], 2),
                                    "forecast_window_peak_predicted_gpus": round(forecast_total_peak, 2),
                                    "forecast_capacity_shortfall_gpus": round(shortfall, 2),
                                    "readiness_capacity_shortfall_gpus": round(readiness_shortfall, 2),
                                    "readiness_shortfall_minutes": readiness_shortfall_minutes,
                                    "pre_warm_active_shortfall_gpus": round(pre_warm_shortfall, 2),
                                    "forecast_margin_gpus": round(margin, 2),
                                    "forecast_margin_source": margin_source,
                                    "forecast_margin_history_windows": len(margin_window_errors),
                                    "target_warm_nodes": target_warm,
                                    "forecast_target_active_nodes": forecast_target_active,
                                    "forecast_warm_nodes_started": forecast_warm_started,
                                    "forecast_cold_nodes_started": forecast_cold_started,
                                    "warm_stock_target_nodes": warm_stock_target,
                                    "warm_overhead_nodes": warm_overhead_nodes,
                                    "queued_reserve_demand_nodes": queued_reserve_demand_nodes,
                                    "warm_stock_shortfall_nodes": warm_stock_shortfall,
                                    "warm_ready_deficit_nodes": max(0, warm_stock_target - warm_now),
                                    "target_warm_fleet_shortfall_nodes": target_warm_fleet_shortfall,
                                    "target_warm_realizable_nodes": target_warm_realizable,
                                    "warm_reserve_ready_nodes": warm_now,
                                    "warm_reserve_pipeline_nodes": pipeline_nodes,
                                    "warm_reserve_pipeline_gap_nodes": reserve_pipeline_gap,
                                    "running_gpus": busy_gpus, "flexible_gpus": round(flex_busy_gpu, 3),
                                    "queued_requests": len(waiting), "active_capacity_gpus": active * gpn, "ready_in_5m_capacity_gpus": (active + warm) * gpn, "active_nodes": active, "warm_nodes": warm,
                                    "booting_nodes": booting_now + warming_now, "off_nodes": n-active-warm-boot})
        # One-minute flexible allocations are commitments, not persistent
        # request reservations; release their physical slots after energy is
        # accounted for at this tick.
        for ni, used in flex_minute_allocations:
            nodes[ni].used = max(0.0, nodes[ni].used - used)
    counts = {state: sum(v["status"] == state for v in statuses.values()) for state in ("completed", "queued", "running", "rejected")}
    for ji, job in enumerate(flex_plan["jobs"]):
        if job.get("admitted") and job.get("status") == "scheduled":
            remaining = max(0.0, job["gpu_hours"] * 60 - flex_done_by_job[ji])
            flexible_gpu_minutes_missed += remaining
            job.update(status="completed" if remaining <= 1e-6 else "deadline_missed",
                       delivered_gpu_hours=flex_done_by_job[ji] / 60,
                       unmet_gpu_hours=remaining / 60, deadline_met=remaining <= 1e-6)
    waits = [v["start"] - v["arrival"] for v in statuses.values() if v.get("start") is not None]
    waits_by_class = {
        name: [value["start"] - value["arrival"] for value in statuses.values()
               if value["class"] == name and value.get("start") is not None]
        for name in CLASSES
    }
    deadlines = sum(v.get("response_minutes", math.inf) <= v["latency"] for v in statuses.values() if v["status"] == "completed")
    metrics = {
        **{k: round(v, 3) for k, v in totals.items()},
        "renewable_curtailed_kwh": round(totals["renewable_curtailed_kwh"], 3),
        "requests_completed": counts["completed"], "requests_queued_at_horizon": counts["queued"],
        "requests_running_at_horizon": counts["running"], "requests_rejected": counts["rejected"],
        "completion_fraction": round(counts["completed"] / max(1, len(requests)), 4),
        "mean_wait_minutes": round(sum(waits) / len(waits), 2) if waits else None,
        "p95_wait_minutes": round(sorted(waits)[min(len(waits)-1, math.ceil(.95*len(waits))-1)], 2) if waits else None,
        "requests_waited": sum(1 for v in statuses.values()
                               if v["status"] == "queued"
                               or (v.get("start") is not None and v["start"] > v["arrival"])),
        "requests_total": len(requests),
        "peak_queued_requests": max((row["queued_requests"] for row in timeline_states), default=0),
        "mean_wait_minutes_by_class": {
            name: round(sum(values) / len(values), 2) if values else None
            for name, values in waits_by_class.items()
        },
        "p95_wait_minutes_by_class": {
            name: round(sorted(values)[min(len(values)-1, math.ceil(.95*len(values))-1)], 2) if values else None
            for name, values in waits_by_class.items()
        },
        "requests_waited_by_class": {
            name: sum(1 for v in statuses.values()
                      if v["class"] == name
                      and (v["status"] == "queued"
                           or (v.get("start") is not None and v["start"] > v["arrival"])))
            for name in CLASSES
        },
        "mean_completion_latency_minutes": round(sum(v["response_minutes"] for v in statuses.values() if v.get("response_minutes") is not None) / max(1, counts["completed"]), 2),
        "latency_allowance_met": deadlines,
        "latency_allowance_total": sum(v["status"] == "completed" for v in statuses.values()),
        "offered_gpu_minutes": sum(offered),
        "served_gpu_minutes": served_gpu_minutes,
        "energy_accounted_gpu_minutes": round(energy_accounted_gpu_minutes, 3),
        "peak_active_nodes": max((x["active_nodes"] for x in timeline_states), default=0),
        "peak_offered_gpu_demand": max(offered, default=0),
        "max_forecast_capacity_shortfall_gpus": max((x["forecast_capacity_shortfall_gpus"] for x in timeline_states), default=0),
        "forecast_shortfall_minutes": sum(5 for x in timeline_states if x["forecast_capacity_shortfall_gpus"] > 0),
        "max_readiness_capacity_shortfall_gpus": max((x["readiness_capacity_shortfall_gpus"] for x in timeline_states), default=0),
        "readiness_shortfall_intervals": sum(1 for x in timeline_states if x["readiness_capacity_shortfall_gpus"] > 0),
        "max_pre_warm_active_shortfall_gpus": max((x["pre_warm_active_shortfall_gpus"] for x in timeline_states), default=0),
        "max_target_warm_fleet_shortfall_nodes": max((x["target_warm_fleet_shortfall_nodes"] for x in timeline_states), default=0),
        "max_target_warm_nodes": max((x["target_warm_nodes"] for x in timeline_states), default=0),
        "max_warm_stock_shortfall_nodes": max((x.get("warm_stock_shortfall_nodes", 0) for x in timeline_states), default=0),
        "max_warm_ready_deficit_nodes": max((x.get("warm_ready_deficit_nodes", 0) for x in timeline_states), default=0),
        "peak_offered_fleet_shortfall_gpus": max((max(0, d - n * gpn) for d in offered), default=0),
        "offered_fleet_shortfall_minutes": sum(d > n * gpn for d in offered),
        "active_capacity_shortfall_gpu_minutes": sum(max(0, offered[row["minute"]] - row["active_nodes"] * gpn) * 5 for row in timeline_states),
        "flexible_jobs_admitted": sum(job.get("admitted", False) for job in flex_plan["jobs"]),
        "flexible_jobs_deadline_met": sum(job.get("deadline_met", False) for job in flex_plan["jobs"]),
        "flexible_gpu_hours_scheduled": round(sum(job["gpu_hours"] for job in flex_plan["jobs"] if job.get("admitted")), 3),
        "flexible_gpu_hours_delivered": round(sum(flex_done_by_job) / 60, 3),
        "flexible_gpu_hours_unmet": round(sum(max(0, job["gpu_hours"] * 60 - flex_done_by_job[i]) for i, job in enumerate(flex_plan["jobs"]) if job.get("admitted")) / 60
                                            + sum(job["gpu_hours"] for job in flex_plan["jobs"] if not job.get("admitted")), 3),
        "flexible_commitment_missed_gpu_minutes": round(flexible_gpu_minutes_missed, 3),
        "flexible_deadline_misses": sum(job.get("admitted") and not job.get("deadline_met", False) for job in flex_plan["jobs"]),
    }
    request_replay = [{
        "id": value["id"], "tier": value["class"], "arrival_minute": value["arrival"],
        "gpus": value["gpus"], "duration_minutes": value["duration"],
        "started_at_minute": value.get("start"),
        "completed_at_minute": value.get("completed_minute"),
        "rejected_at_minute": value.get("rejected_minute"),
        "status": value["status"],
    } for value in statuses.values()]
    return {"label": policy.replace("_", " ").title(), "metrics": metrics,
            # Preserve enough precision that the 24 displayed rows reconcile
            # to the run total; the UI applies human-readable rounding.
            "hourly_grid_costs": [{**row,
                                   "grid_kwh": round(row["grid_kwh"], 6),
                                   "renewable_used_kwh": round(row["renewable_used_kwh"], 6),
                                   "facility_kwh": round(row["facility_kwh"], 6),
                                   "emissions_kg": round(row["emissions_kg"], 6),
                                   "cost_cny": round(row["cost_cny"], 6)} for row in hourly_grid_costs],
            "state_trace": timeline_states,
            "request_status_counts": counts,
            "flexible_jobs": flex_plan["jobs"], "flexible_admission_status": flex_plan["admission_status"],
            "flexible_admission_reason": flex_plan["admission_reason"],
            "replay": {"node_ids": [f"node-{i + 1:02d}" for i in range(n)],
                       "frames": replay_frames, "requests": request_replay,
                       "forecast_debug": forecast_debug}}



def _forecast_v2_curve(forecaster: ForecasterV2, minute: int, running: dict[str, dict[str, Any]],
                       waiting: deque[str], statuses: dict[str, dict[str, Any]], nodes: list[Node],
                       flex_plan: dict[str, Any], flex_done_by_job: list[float], gpn: int,
                       horizon: int) -> tuple[list[float], list[float], list[float], list[float],
                                              list[float], list[float], float, str, int, list[float]]:
    """Build the information-restricted inputs the v2 forecaster is allowed to see.

    Note what is *not* passed: request durations, running end minutes, or the LP
    hourly rate vector. The forecaster must infer all three.
    """
    running_views = [
        RunningJob(statuses[rid]["class"], int(job["gpus"]),
                   max(0, minute - int(statuses[rid]["start"])))
        for rid, job in running.items()
    ]
    queued_views = [
        QueuedJob(statuses[rid]["class"], int(statuses[rid]["gpus"]),
                  int(statuses[rid]["arrival"]), rid)
        for rid in waiting
    ]
    node_views = [NodeView(node.state, int(node.remaining)) for node in nodes]
    flex_views = []
    for index, job in enumerate(flex_plan["jobs"]):
        if not job.get("admitted"):
            continue
        # Only work whose release window has actually opened can consume capacity.
        if int(job["arrival"]) * 60 > minute:
            continue
        remaining = max(0.0, float(job["gpu_hours"]) * 60 - flex_done_by_job[index])
        minutes_left = int(job["deadline"]) * 60 - minute
        if remaining > 1e-9 and minutes_left > 0:
            flex_views.append(FlexCommitment(remaining, minutes_left, float(job["max_gpus"])))
    result = forecaster.predict(minute, running_views, queued_views, node_views, flex_views)
    return (result.predicted_by_offset, result.upper_by_offset, result.new_arrivals_by_offset,
            result.running_by_offset, result.queue_by_offset, result.flex_by_offset,
            result.margin_gpus, result.margin_source, result.unplaced_queue_jobs,
            result.margins_by_bucket)


def _scale_up(nodes: list[Node], target_active: int, gpn: int) -> None:
    active = sum(x.state == "active" for x in nodes)
    pending = sum(x.state == "warming" or (x.state == "booting" and x.purpose == "activation") for x in nodes)
    deficit = max(0, target_active - active - pending)
    for node in nodes:
        if not deficit:
            break
        if node.state == "warm":
            node.state, node.remaining, node.purpose = "active", 0, None
            deficit -= 1
    for node in nodes:
        if not deficit:
            break
        if node.state == "off":
            node.state, node.remaining, node.purpose = "booting", COLD_BOOT_TO_WARM_MINUTES, "activation"
            deficit -= 1


def _choose_waiting_request(waiting: deque[str], statuses: dict[str, dict[str, Any]], minute: int, free_gpus: int,
                            admissible=None, queue_policy="interactive_batch") -> str | None:
    can_start = admissible or (lambda _rid: True)
    if queue_policy == "fifo_next_fit":
        candidates = sorted(waiting, key=lambda rid: (statuses[rid]["arrival"], rid))
        return next((rid for rid in candidates if statuses[rid]["gpus"] <= free_gpus and can_start(rid)), None)
    aged_batch = sorted((rid for rid in waiting if statuses[rid]["class"] == "batch"
                         and minute - statuses[rid]["arrival"] >= 15),
                        key=lambda rid: (statuses[rid]["arrival"], rid))
    if aged_batch:
        # Protect the oldest aged batch request from being perpetually
        # backfilled by newer arrivals while it waits for enough free GPUs.
        head = aged_batch[0]
        return head if statuses[head]["gpus"] <= free_gpus and can_start(head) else None
    candidates = sorted(waiting, key=lambda rid: (
        0 if statuses[rid]["class"] == "interactive" else 1,
        statuses[rid]["arrival"], rid,
    ))
    return next((rid for rid in candidates if statuses[rid]["gpus"] <= free_gpus and can_start(rid)), None)


def _flex_rate_at(hourly_rates: list[list[float]], minute: int) -> float:
    hour = minute // 60
    if hour >= 24:
        return 0.0
    return sum(row[hour] for row in hourly_rates)


def _known_flex_peak(hourly_rates: list[list[float]], minute: int, horizon: int) -> float:
    return max((_flex_rate_at(hourly_rates, m) for m in range(minute, min(MINUTES_PER_DAY, minute + horizon + 1))), default=0.0)


def _reservation_at(plan: dict[str, Any], minute: int) -> float:
    return plan["realtime_reservation_gpus"][min(23, minute // 60)] if minute < MINUTES_PER_DAY else 0.0


def _required_capacity_peak(plan: dict[str, Any], minute: int, horizon: int,
                            realtime_upper: float = 0.0) -> float:
    """Peak contemporaneous capacity need; do not sum maxima from different minutes."""
    end = min(MINUTES_PER_DAY, minute + horizon + 1)
    return max((
        _flex_rate_at(plan["hourly_rates"], m)
        + max(realtime_upper, _reservation_at(plan, m))
        for m in range(minute, end)
    ), default=0.0)


def _allocate_active(nodes: list[Node], amount: float, gpn: int) -> tuple[float, list[tuple[int, float]]]:
    left = max(0.0, amount)
    allocations = []
    for ni, node in enumerate(nodes):
        if node.state != "active":
            continue
        available = max(0.0, gpn - node.used)
        take = min(left, available)
        if take > 1e-9:
            node.used += take
            allocations.append((ni, take))
            left -= take
        if left <= 1e-9:
            break
    return amount - left, allocations


def _projected_active_capacity(nodes: list[Node], minutes_ahead: int, gpn: int) -> int:
    ready = 0
    for node in nodes:
        if node.state == "active" or (node.state == "warming" and node.remaining <= minutes_ahead):
            ready += 1
        elif node.state == "warm":
            ready += 1 if minutes_ahead >= WARM_START_MINUTES else 0
        elif node.state == "booting" and node.remaining + WARM_START_MINUTES <= minutes_ahead:
            ready += 1
        elif node.state == "off" and minutes_ahead >= COLD_TO_ACTIVE_MINUTES:
            # A powered-off node is usable only if the causal controller has
            # actually initiated its cold boot; never assume an unissued action.
            continue
    return ready * gpn


def _request_preserves_flexible_commitments(candidate_id: str, candidate: dict[str, Any], minute: int,
                                            running: dict[str, dict[str, Any]], nodes: list[Node],
                                            gpn: int, plan: dict[str, Any]) -> bool:
    end = min(MINUTES_PER_DAY, minute + candidate["duration"])
    for future in range(minute, end):
        capacity = _projected_active_capacity(nodes, future - minute, gpn)
        occupied = sum(job["gpus"] for job in running.values() if job["end"] > future)
        if future < end:
            occupied += candidate["gpus"]
        if occupied + _flex_rate_at(plan["hourly_rates"], future) > capacity + 1e-9:
            return False
    return True


def _ensure_warm_reserve(nodes: list[Node], target_warm: int) -> None:
    counted = _warm_stock_pipeline_nodes(nodes)
    deficit = max(0, target_warm - counted)
    for node in nodes:
        if not deficit:
            break
        if node.state == "off":
            node.state, node.remaining, node.purpose = "booting", COLD_BOOT_TO_WARM_MINUTES, "warm_stock"
            deficit -= 1


def _queued_reserve_demand_nodes(waiting: deque[str], statuses: dict[str, dict[str, Any]],
                                 gpus_per_node: int, fleet_nodes: int) -> int:
    """Convert the remaining real-time GPU queue into a bounded node target."""
    queued_gpus = sum(float(statuses[rid]["gpus"]) for rid in waiting)
    return min(fleet_nodes, math.ceil(queued_gpus / gpus_per_node)) if queued_gpus else 0


def _warm_stock_pipeline_nodes(nodes: list[Node]) -> int:
    """Count ready warm nodes and nodes booting toward warm standby.

    Nodes in ``warming`` are already reserved for activation, not available
    warm stock, so a replacement boot must be planned for them.
    """
    return sum(node.state == "warm" or (node.state == "booting" and node.purpose == "warm_stock")
               for node in nodes)


def _advance_transitions(nodes: list[Node]) -> None:
    for node in nodes:
        if node.state in ("booting", "warming"):
            node.remaining -= 1
            if node.remaining <= 0:
                node.state = "warm" if node.state == "booting" else "active"
                node.purpose = None
