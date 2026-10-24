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

MINUTES_PER_DAY = 24 * 60
BUCKET = 5
CLASSES = {
    "interactive": {"rate_per_5m": 6.0, "gpu": (1, 2), "duration": (2, 5, 8), "latency": 2},
    "batch": {"rate_per_5m": 2.0, "gpu": (2, 4), "duration": (5, 15, 30), "latency": 30},
}
TOU_PRICE_CNY = [0.38648119 if h < 8 else 0.83855171 if h in (10, 11, 15, 16, 17, 18, 19, 20, 21) else 0.62185675 for h in range(24)]
GRID_CO2_KG_KWH = 0.55
WARM_START_MINUTES = 5
COLD_BOOT_TO_WARM_MINUTES = 20
COLD_TO_ACTIVE_MINUTES = COLD_BOOT_TO_WARM_MINUTES + WARM_START_MINUTES
MARGIN_HISTORY_WINDOWS_REQUIRED = 28
MARGIN_QUANTILE = 0.95


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


def generate_requests(seed: int, *, burst: bool = True) -> list[dict[str, Any]]:
    """Generate one seeded day; service durations are fixed on arrival."""
    rng = random.Random(seed)
    burst_starts = set()
    if burst and rng.random() < 0.25:
        burst_starts.add(rng.randrange(0, MINUTES_PER_DAY - 15))
    records = []
    for start in range(0, MINUTES_PER_DAY, BUCKET):
        burst_multiplier = 3.0 if any(b <= start < b + 15 for b in burst_starts) else 1.0
        for name, cfg in CLASSES.items():
            n = _poisson(rng, cfg["rate_per_5m"] * _tod(start) * burst_multiplier)
            for _ in range(n):
                gpus = rng.randint(*cfg["gpu"])
                duration = round(rng.triangular(*cfg["duration"]))
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
    factors = {}
    for name, cfg in CLASSES.items():
        mean_gpus = (cfg["gpu"][0] + cfg["gpu"][1]) / 2
        mean_duration = sum(cfg["duration"]) / 3
        factors[name] = mean_gpus * mean_duration
    return factors


def _arrival_rate_forecasts(requests: list[dict[str, Any]], alpha: float = 0.3,
                            *, generator_prior: bool = True) -> list[dict[str, float]]:
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
    rates = ({name: cfg["rate_per_5m"] * _tod(0) / BUCKET for name, cfg in CLASSES.items()}
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
    """Expected concurrent GPU demand from future arrivals (lambda × GPU-min/request)."""
    current_factor = max(_tod(minute), 1e-9)
    future_factor = _tod(horizon_minute)
    diurnal_scale = future_factor / current_factor
    return sum(rates[name] * diurnal_scale * work_factors[name] for name in CLASSES)


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
        if offset < WARM_START_MINUTES:
            pre_warm_peak = max(pre_warm_peak, shortfall)
    return peak, affected, pre_warm_peak


@dataclass
class Node:
    state: str
    remaining: int = 0
    idle: int = 0
    used: int = 0


def _validate(payload: dict[str, Any]) -> tuple[int, int, int]:
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
    gpn = whole_number(payload.get("gpus_per_node", 8), "GPUs per node")
    seed = whole_number(payload.get("seed", 2026), "Seed")
    if not 2 <= nodes <= 64 or not 1 <= gpn <= 16 or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Use 2–64 nodes, 1–16 GPUs per node, and a nonnegative 32-bit seed.")
    return nodes, gpn, seed


def run_dynamic_comparison(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run identical offered requests under always-on, reactive, and forecast control."""
    payload = payload or {}
    n, gpn, seed = _validate(payload)
    try:
        alpha = float(payload.get("forecast_alpha", 0.3))
        margin_fraction = float(payload.get("margin_fraction", 0.15))
        margin_floor_gpus = float(payload.get("margin_floor_gpus", 4.0))
        min_active_fraction = float(payload.get("min_active_fraction", 0.25))
    except (TypeError, ValueError):
        raise ValueError("Forecast alpha and margin fraction must be numbers.") from None
    if (not 0.05 <= alpha <= 0.8 or not 0 <= margin_fraction <= 1
            or not math.isfinite(margin_floor_gpus) or margin_floor_gpus < 0
            or not 0 <= min_active_fraction <= 1):
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
    requests = _validate_request_trace(payload.get("request_trace"), n * gpn) if payload.get("request_trace") is not None else generate_requests(seed, burst=bool(payload.get("bursts", True)))
    offered = _offered_gpu_trace(requests)
    flex_plan = _prepare_flexible_plan(n * gpn, payload.get("flexible_jobs"))
    # Forecast series are causal by construction: each bucket uses only prior
    # completed arrival counts; synthetic generator rates seed the first bucket.
    arrival_rates = _arrival_rate_forecasts(requests, alpha, generator_prior=payload.get("request_trace") is None)
    policies = {name: _run_policy(requests, offered, arrival_rates, work_factors, n, gpn, seed,
                                   alpha, margin_fraction, margin_floor_gpus, min_active_nodes,
                                   name, deepcopy(flex_plan))
                for name in ("always_on", "reactive", "forecast")}
    baseline_plan = _greedy_asap_plan(flex_plan, n * gpn)
    baseline_run = _run_policy(requests, offered, arrival_rates, work_factors, n, gpn, seed,
                               alpha, margin_fraction, margin_floor_gpus, min_active_nodes,
                               "always_on", baseline_plan, queue_policy="fifo_next_fit")
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
    forecast_policy = policies["forecast"]
    margin_sources = sorted({row["forecast_margin_source"] for row in forecast_policy["state_trace"]})
    return {
        "seed": seed, "nodes": n, "gpus_per_node": gpn, "fleet_gpus": n * gpn,
        "requests_generated": len(requests), "offered_peak_gpus": max(offered, default=0),
        "forecast_margin_rule": (f"95th percentile of matured prior window-maximum positive residuals after {MARGIN_HISTORY_WINDOWS_REQUIRED} windows; "
                                 f"otherwise max({margin_floor_gpus:g} GPUs, {margin_fraction:.0%} of predicted total demand)"),
        "selected_policy": "forecast", "forecast_alpha": alpha, "margin_fraction": margin_fraction,
        "margin_floor_gpus": margin_floor_gpus,
        "minimum_active_nodes": min_active_nodes,
        "flexible_schedule": {k: v for k, v in flex_plan.items() if k not in {"schedule", "jobs", "hourly_rates", "realtime_reservation_gpus"}}
        | {"scheduled_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"] if job.get("admitted")), 3),
           "candidate_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"]), 3)},
        "flexible_jobs": flex_plan["jobs"],
        "policies": policies,
        "unscheduled_baseline": baseline,
        "comparisons": comparisons,
        "assumptions": {
            "data_status": "synthetic_illustrative_not_measurements",
            "demand_model": "seeded Poisson requests; 5-minute arrivals; triangular service durations; optional hidden 3x bursts",
            "forecast": (f"5-minute causal per-class arrival-rate EWMA (alpha={alpha:g}; requests/minute) times the class GPU-minutes/request factors; "
                         f"initialized from {'the declared synthetic generator baseline' if payload.get('request_trace') is None else 'zero for the explicit request trace'} and adjusted by its known diurnal profile; includes current running requests exactly and amortizes queued GPU-minutes across the warm/cold bridge"),
            "arrival_rate_initial_prior": "synthetic generator baseline; not observed history" if payload.get("request_trace") is None else "zero; explicit trace arrivals update future buckets causally",
            "forecast_workload_gpu_minutes_per_request": work_factors,
            "forecast_calibration_limit": (f"Matured forecast window errors are accumulated causally within this synthetic run; after {MARGIN_HISTORY_WINDOWS_REQUIRED} complete windows the 95th percentile is used. "
                                            "No measured multi-day history or independent real-data calibration is supplied; before the threshold the manual fallback applies."),
            "forecast_margin_sources_seen": margin_sources,
            "forecast_margin_fallback": f"max({margin_floor_gpus:g} GPUs, {margin_fraction:.0%} of predicted total GPU demand); scenario assumption, not a calibrated confidence bound",
            "warm_reserve_equation": "W_target=ceil(max(0,max(U_t(h), tau_w<=h<tau_c)-C_t)/g); C_t=g*A_t includes active spare; W_target is not clipped to fleet",
            "warm_reserve_window_minutes": f"{WARM_START_MINUTES} <= h < {COLD_TO_ACTIVE_MINUTES}",
            "warm_queue_forecast_approximation": "Known queued GPU-minutes, capped per request to the bridge-window duration, divided by bridge-window minutes; transparent average backlog pressure, not a dispatch simulation",
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
            "flexible_jobs": "The existing hourly Pro-priority LP provides one fixed, shared 24-hour GPU-hour schedule for all node policies. Its fixed realtime curve is a capacity reservation only; generated requests replace that placeholder in minute-level energy accounting. LP-infeasible flexible candidates are explicitly not admitted. No runtime reallocation or preemption is performed.",
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
                *, queue_policy="interactive_batch"):
    first_hour_flex = sum(row[0] for row in flex_plan["hourly_rates"])
    first_hour_reservation = flex_plan["realtime_reservation_gpus"][0]
    first_hour_nodes = math.ceil((first_hour_flex + first_hour_reservation) / gpn)
    initial_active = n if policy == "always_on" else min(n, max(2, n // 2, first_hour_nodes))
    nodes = [Node("active" if i < initial_active else "warm" if i < initial_active + 2 else "off") for i in range(n)]
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
    served_gpu_minutes = 0
    energy_accounted_gpu_minutes = 0.0
    flexible_gpu_minutes_missed = 0.0
    flexible_hour_delivered = [[0.0] * 24 for _ in flex_plan["jobs"]]
    flex_done_by_job = [0.0] * len(flex_plan["jobs"])
    flex_minute_allocations: list[tuple[int, float]] = []
    margin_window_errors: list[float] = []
    issued_window_forecasts: dict[int, dict[int, float]] = {}
    forecast = upper = forecast_realtime = forecast_running = forecast_queue = forecast_flex = 0.0
    forecast_window_peak = 0.0
    margin = margin_floor_gpus
    margin_source = "manual_assumption_fallback"
    target_warm = target_warm_fleet_shortfall = target_warm_realizable = 0
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
                del running[rid]
        # Finish jobs whose declared deadline is at this boundary; any planned
        # work that could not run before it is an explicit miss, never silently
        # rescheduled past the deadline.
        for ji, job in enumerate(flex_plan["jobs"]):
            if job.get("admitted") and job["deadline"] * 60 == minute:
                remaining = max(0.0, job["gpu_hours"] * 60 - flex_done_by_job[ji])
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

        # Mature only issued forecasts whose entire requested minute has now
        # been observed. Residuals use offered demand at this minute, not future
        # trace values exposed before their timestamp.
        if policy == "forecast":
            actual_total = offered[minute] + _flex_rate_at(flex_plan["hourly_rates"], minute)
            for issue_minute, predictions in list(issued_window_forecasts.items()):
                if minute in predictions:
                    predictions[minute] = max(0.0, actual_total - predictions[minute])
                if minute == issue_minute + COLD_TO_ACTIVE_MINUTES - 1:
                    margin_window_errors.append(max(predictions.values(), default=0.0))
                    del issued_window_forecasts[issue_minute]

        # Causal reserve update every five minutes. The adopted target window
        # is [warm-to-active, fully-off-to-active), with total demand evaluated
        # minute-by-minute so flexible commitments are paired at the same time.
        if minute % BUCKET == 0:
            rates = arrival_rates[min(minute // BUCKET, len(arrival_rates) - 1)]
            bridge_minutes = COLD_TO_ACTIVE_MINUTES - WARM_START_MINUTES
            queued_pressure = _known_queued_gpu_pressure(waiting, statuses, bridge_minutes)
            predicted_by_offset: dict[int, float] = {}
            realtime_by_offset: dict[int, float] = {}
            running_by_offset: dict[int, float] = {}
            flex_by_offset: dict[int, float] = {}
            for offset in range(COLD_TO_ACTIVE_MINUTES):
                future_minute = minute + offset
                future_flex = _flex_rate_at(flex_plan["hourly_rates"], future_minute)
                future_running = _known_running_gpu_demand(running, future_minute)
                future_arrivals = _expected_realtime_gpu_demand(rates, minute, future_minute, work_factors)
                realtime = future_arrivals + future_running + queued_pressure
                predicted_by_offset[offset] = realtime + future_flex
                realtime_by_offset[offset] = future_arrivals
                running_by_offset[offset] = future_running
                flex_by_offset[offset] = future_flex

            bridge_offsets = list(range(WARM_START_MINUTES, COLD_TO_ACTIVE_MINUTES))
            forecast_total_peak = max((predicted_by_offset[offset] for offset in bridge_offsets), default=0.0)
            forecast_peak_offset = max(bridge_offsets, key=lambda offset: predicted_by_offset[offset], default=WARM_START_MINUTES)
            forecast_window_peak = forecast_total_peak
            margin, margin_source = _forecast_margin(margin_window_errors, forecast_total_peak,
                                                    margin_fraction, margin_floor_gpus)
            upper_by_offset = [(offset, predicted_by_offset[offset] + margin)
                               for offset in range(COLD_TO_ACTIVE_MINUTES)]
            upper = predicted_by_offset[0] + margin
            forecast = realtime_by_offset[0]
            forecast_realtime = realtime_by_offset[0]
            forecast_running = running_by_offset[0]
            forecast_queue = queued_pressure
            forecast_flex = flex_by_offset[0]
            if policy == "forecast":
                active_nodes = sum(x.state == "active" for x in nodes)
                reserve = _warm_target([predicted_by_offset[offset] + margin for offset in bridge_offsets],
                                       active_nodes, n, gpn)
                target_warm = reserve["target_warm_nodes"]
                target_warm_fleet_shortfall = reserve["target_warm_fleet_shortfall_nodes"]
                target_warm_realizable = reserve["target_warm_realizable_nodes"]
                peak_fleet_shortfall = reserve["peak_fleet_shortfall_gpus"]
                readiness_shortfall, readiness_shortfall_minutes, pre_warm_shortfall = _readiness_shortfalls(
                    upper_by_offset, nodes, gpn)
                predicted_by_minute = {minute + offset: value for offset, value in predicted_by_offset.items()
                                       if offset in bridge_offsets and minute + offset < MINUTES_PER_DAY}
                issued_window_forecasts[minute] = predicted_by_minute
                _ensure_warm_reserve(nodes, target_warm)
                reserve_pipeline = sum(x.state in ("warm", "warming", "booting") for x in nodes)
                reserve_pipeline_gap = max(0, target_warm - reserve_pipeline)
            else:
                target_warm = target_warm_fleet_shortfall = target_warm_realizable = 0
                readiness_shortfall = pre_warm_shortfall = peak_fleet_shortfall = 0.0
                readiness_shortfall_minutes = reserve_pipeline_gap = 0
        planned_flex = _flex_rate_at(flex_plan["hourly_rates"], minute)
        # Known accepted LP work is brought online 25 minutes before its
        # commitment (20m cold-to-warm + 5m warm-to-active).
        if policy != "always_on":
            known_peak = _required_capacity_peak(flex_plan, minute, COLD_TO_ACTIVE_MINUTES)
            known_target = min(n, math.ceil(known_peak / gpn))
            _scale_up(nodes, max(known_target, math.ceil(planned_flex / gpn)), gpn)
        # Arrivals remain preserved in the queue; over-capacity requests above
        # are explicitly rejected rather than disappearing from offered load.
        if policy != "always_on" and waiting:
            required = math.ceil((planned_flex + sum(r["gpus"] for r in running.values()) + sum(statuses[r]["gpus"] for r in waiting)) / gpn)
            _scale_up(nodes, min(n, required), gpn)
        # Execute the already-admitted hourly LP commitment first. Real-time
        # dispatch may use only uncommitted active capacity.
        flex_busy_gpu = 0.0
        if flex_plan["admission_status"] == "admitted":
            hour = minute // 60
            for ji, job in enumerate(flex_plan["jobs"]):
                rate = flex_plan["hourly_rates"][ji][hour]
                if rate <= 1e-9 or not job.get("admitted"):
                    continue
                planned_remaining = max(0.0, rate * 60 - flexible_hour_delivered[ji][hour])
                # Keep the LP's minute-average commitment; if temporary lack
                # of active slots occurs, the missed GPU-minutes are visible.
                desired = min(rate, planned_remaining)
                allocated, alloc_nodes = _allocate_active(nodes, desired, gpn)
                flex_busy_gpu += allocated
                flex_done_by_job[ji] += allocated
                flexible_hour_delivered[ji][hour] += allocated
                flex_minute_allocations.extend(alloc_nodes)
                flexible_gpu_minutes_missed += desired - allocated
        # Serve interactive before batch; 15-minute aging protects batch starts.
        while waiting:
            free = [(ni, gpn - node.used) for ni, node in enumerate(nodes) if node.state == "active"]
            free_gpu = sum(x for _, x in free)
            if not free_gpu:
                break
            rid = _choose_waiting_request(waiting, statuses, minute, free_gpu,
                admissible=lambda candidate: _request_preserves_flexible_commitments(
                    candidate, statuses[candidate], minute, running, nodes, gpn, flex_plan),
                queue_policy=queue_policy)
            if rid is None:
                break
            waiting.remove(rid)
            req = statuses[rid]
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
            desired_warm = target_warm if policy == "forecast" else 0
            for ni in reversed(warm_ids):
                node = nodes[ni]
                node.idle += 1
                if len([x for x in nodes if x.state == "warm"]) > desired_warm and node.idle >= 30:
                    node.state = "off"
                    node.idle = 0
            # Forecast controller replenishes its warm target at the next
            # bucket; reactive control intentionally keeps no forecast reserve.
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
        totals["emissions_kg"] += grid * GRID_CO2_KG_KWH
        # Preserve an actual one-minute playback frame. Per-node power is IT
        # draw before shared site overhead/PUE; facility_kw includes both.
        node_power = [
            (1.0 if node.state == "active" else 0.25 if node.state == "warm" else 1.2 if node.state in ("warming", "booting") else 0.0)
            + 0.35 * node.used
            for node in nodes
        ]
        replay_frames.append({
            "minute": minute,
            "states": [node.state for node in nodes],
            "used_gpus": [round(float(node.used), 3) for node in nodes],
            "power_kw": [round(value, 4) for value in node_power],
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
            pipeline_nodes = warm_now + booting_now + warming_now
            reserve_pipeline_gap = max(0, target_warm - pipeline_nodes) if policy == "forecast" else 0
            total_upper = forecast_window_peak + margin
            shortfall = peak_fleet_shortfall if policy == "forecast" else 0.0
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
            job.update(status="completed" if remaining <= 1e-6 else "deadline_missed",
                       delivered_gpu_hours=flex_done_by_job[ji] / 60,
                       unmet_gpu_hours=remaining / 60, deadline_met=remaining <= 1e-6)
    waits = [v["wait_minutes"] for v in statuses.values() if v.get("wait_minutes") is not None]
    deadlines = sum(v.get("response_minutes", math.inf) <= v["latency"] for v in statuses.values() if v["status"] == "completed")
    metrics = {
        **{k: round(v, 3) for k, v in totals.items()},
        "renewable_curtailed_kwh": round(totals["renewable_curtailed_kwh"], 3),
        "requests_completed": counts["completed"], "requests_queued_at_horizon": counts["queued"],
        "requests_running_at_horizon": counts["running"], "requests_rejected": counts["rejected"],
        "completion_fraction": round(counts["completed"] / max(1, len(requests)), 4),
        "mean_wait_minutes": round(sum(waits) / len(waits), 2) if waits else None,
        "p95_wait_minutes": round(sorted(waits)[min(len(waits)-1, math.ceil(.95*len(waits))-1)], 2) if waits else None,
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
    return {"label": policy.replace("_", " ").title(), "metrics": metrics, "state_trace": timeline_states,
            "request_status_counts": counts,
            "flexible_jobs": flex_plan["jobs"], "flexible_admission_status": flex_plan["admission_status"],
            "flexible_admission_reason": flex_plan["admission_reason"],
            "replay": {"node_ids": [f"node-{i + 1:02d}" for i in range(n)],
                       "frames": replay_frames, "requests": request_replay}}


def _scale_up(nodes: list[Node], target_active: int, gpn: int) -> None:
    active = sum(x.state == "active" for x in nodes)
    pending = sum(x.state in ("warming", "booting") for x in nodes)
    deficit = max(0, target_active - active - pending)
    for node in nodes:
        if not deficit:
            break
        if node.state == "warm":
            node.state, node.remaining = "warming", 5
            deficit -= 1
    for node in nodes:
        if not deficit:
            break
        if node.state == "off":
            node.state, node.remaining = "booting", 20
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
            ready += 1 if minutes_ahead >= 5 else 0
        elif node.state == "booting" and node.remaining + 5 <= minutes_ahead:
            ready += 1
        elif node.state == "off" and minutes_ahead >= 25:
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
    counted = sum(x.state in ("warm", "warming", "booting") for x in nodes)
    deficit = max(0, target_warm - counted)
    for node in nodes:
        if not deficit:
            break
        if node.state == "off":
            node.state, node.remaining = "booting", 20
            deficit -= 1


def _advance_transitions(nodes: list[Node]) -> None:
    for node in nodes:
        if node.state in ("booting", "warming"):
            node.remaining -= 1
            if node.remaining <= 0:
                node.state = "warm" if node.state == "booting" else "active"
