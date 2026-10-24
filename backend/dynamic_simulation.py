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


def _forecast_series(trace: list[int], alpha: float = 0.3) -> tuple[list[float], list[float]]:
    """Causal EWMA of observed offered demand; each value uses only earlier buckets."""
    actual, forecast = [], []
    state = 0.0
    for b in range(MINUTES_PER_DAY // BUCKET):
        sample = max(trace[b * BUCKET:(b + 1) * BUCKET], default=0)
        actual.append(float(sample))
        forecast.append(state)
        state = alpha * sample + (1 - alpha) * state
    return actual, forecast


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
        min_active_fraction = float(payload.get("min_active_fraction", 0.25))
    except (TypeError, ValueError):
        raise ValueError("Forecast alpha and margin fraction must be numbers.") from None
    if not 0.05 <= alpha <= 0.8 or not 0 <= margin_fraction <= 1 or not 0 <= min_active_fraction <= 1:
        raise ValueError("Forecast alpha must be 0.05–0.8; margin and minimum-active fractions must be 0–1.")
    min_active_nodes = min(n, max(1, math.ceil(n * min_active_fraction)))
    requests = _validate_request_trace(payload.get("request_trace"), n * gpn) if payload.get("request_trace") is not None else generate_requests(seed, burst=bool(payload.get("bursts", True)))
    offered = _offered_gpu_trace(requests)
    flex_plan = _prepare_flexible_plan(n * gpn, payload.get("flexible_jobs"))
    # Current day is used to form the diagnostic forecast; actions at bucket b
    # see only maxima from buckets strictly before b.
    _, forecast_b = _forecast_series(offered, alpha)
    # No independent historical error archive exists yet. The explicitly
    # uncalibrated fallback is calculated from the forecast at each decision,
    # never from the current day's later realized demand.
    policies = {name: _run_policy(requests, offered, forecast_b, n, gpn, seed, margin_fraction, min_active_nodes, name, deepcopy(flex_plan))
                for name in ("always_on", "reactive", "forecast")}
    return {
        "seed": seed, "nodes": n, "gpus_per_node": gpn, "fleet_gpus": n * gpn,
        "requests_generated": len(requests), "offered_peak_gpus": max(offered, default=0),
        "forecast_margin_rule": f"max(4 GPUs, {margin_fraction:.0%} of the current causal forecast)", "selected_policy": "forecast",
        "forecast_alpha": alpha, "margin_fraction": margin_fraction,
        "minimum_active_nodes": min_active_nodes,
        "flexible_schedule": {k: v for k, v in flex_plan.items() if k not in {"schedule", "jobs", "hourly_rates", "realtime_reservation_gpus"}}
        | {"scheduled_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"] if job.get("admitted")), 3),
           "candidate_gpu_hours": round(sum(job["gpu_hours"] for job in flex_plan["jobs"]), 3)},
        "flexible_jobs": flex_plan["jobs"],
        "policies": policies,
        "assumptions": {
            "data_status": "synthetic_illustrative_not_measurements",
            "demand_model": "seeded Poisson requests; 5-minute arrivals; triangular service durations; optional hidden 3x bursts",
            "forecast": f"5-minute causal EWMA (alpha={alpha:g}) of offered concurrent GPU demand; initialization at zero; current forecast error history is not available, so max(4 GPUs, {margin_fraction:.0%} forecast) is used",
            "forecast_calibration_limit": "No independent historical forecast archive or calibrated quantile exists; the fallback is not a guarantee",
            "minimum_active_floor": f"{min_active_nodes} active nodes ({min_active_fraction:.0%} of inventory), an explicit illustrative floor for short-latency service; not demand-derived",
            "node_control": "GPU allocation granularity; whole-node active/warm/boot/off states; no independent GPU power-gating assumed",
            "warm_start_minutes": 5, "cold_to_warm_minutes": 20,
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


def _run_policy(requests, offered, forecast_b, n, gpn, seed, margin_fraction, min_active_nodes, policy, flex_plan):
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
    timeline_states, hist_wait, hist_energy = [], [], []
    # time-weighted accounting at one-minute resolution
    totals = {k: 0.0 for k in ("facility_kwh", "grid_kwh", "renewable_used_kwh", "renewable_curtailed_kwh", "cost_cny", "emissions_kg")}
    served_gpu_minutes = 0
    energy_accounted_gpu_minutes = 0.0
    flexible_gpu_minutes_missed = 0.0
    flexible_hour_delivered = [[0.0] * 24 for _ in flex_plan["jobs"]]
    flex_done_by_job = [0.0] * len(flex_plan["jobs"])
    flex_minute_allocations: list[tuple[int, float]] = []
    forecast_idx = 0
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
        # causal controller update at each 5-minute boundary
        target_warm = 0
        forecast = 0.0
        upper = 0.0
        if minute % BUCKET == 0:
            forecast = forecast_b[forecast_idx] if forecast_idx < len(forecast_b) else 0
            margin = max(4.0, margin_fraction * forecast)
            upper = forecast + margin
            forecast_idx += 1
            if policy == "forecast":
                active_capacity = sum(x.state == "active" for x in nodes) * gpn
                known_peak = _required_capacity_peak(flex_plan, minute, 25, upper)
                target_warm = min(n - sum(x.state == "active" for x in nodes),
                                  math.ceil(max(0, known_peak - active_capacity) / gpn))
                _ensure_warm_reserve(nodes, target_warm)
        planned_flex = _flex_rate_at(flex_plan["hourly_rates"], minute)
        # Known accepted LP work is brought online 25 minutes before its
        # commitment (20m cold-to-warm + 5m warm-to-active).
        if policy != "always_on":
            known_peak = _required_capacity_peak(flex_plan, minute, 25)
            known_target = min(n, math.ceil(known_peak / gpn))
            _scale_up(nodes, max(known_target, math.ceil(planned_flex / gpn)), gpn)
        # arrivals preserved, unlimited queue; over-capacity requests are explicit reject only if > fleet
        for r in arrived_at.get(minute, []):
            if r["gpus"] > n * gpn:
                statuses[r["id"]].update(status="rejected", reason="Request exceeds installed fleet")
            elif len(waiting) >= 256:
                statuses[r["id"]].update(status="rejected", reason="Queue reached the 256-request scenario limit")
            else:
                statuses[r["id"]]["status"] = "queued"
                waiting.append(r["id"])
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
                    candidate, statuses[candidate], minute, running, nodes, gpn, flex_plan))
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
        if minute % 5 == 0:
            forecast_flex = _known_flex_peak(flex_plan["hourly_rates"], minute, 25)
            total_upper = _required_capacity_peak(flex_plan, minute, 25, upper)
            shortfall = max(0.0, total_upper - n * gpn)
            timeline_states.append({"minute": minute, "offered_gpus": offered[minute], "forecast_gpus": round(forecast, 2), "forecast_upper_gpus": round(upper, 2), "flexible_commitment_gpus": round(forecast_flex, 2), "forecast_total_upper_gpus": round(total_upper, 2), "forecast_capacity_shortfall_gpus": round(shortfall, 2), "target_warm_nodes": target_warm, "running_gpus": busy_gpus, "flexible_gpus": round(flex_busy_gpu, 3),
                                    "queued_requests": len(waiting), "active_capacity_gpus": active * gpn, "ready_in_5m_capacity_gpus": (active + warm) * gpn, "active_nodes": active, "warm_nodes": warm,
                                    "booting_nodes": boot, "off_nodes": n-active-warm-boot})
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
    return {"label": policy.replace("_", " ").title(), "metrics": metrics, "state_trace": timeline_states,
            "request_status_counts": counts,
            "flexible_jobs": flex_plan["jobs"], "flexible_admission_status": flex_plan["admission_status"],
            "flexible_admission_reason": flex_plan["admission_reason"]}


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
                            admissible=None) -> str | None:
    can_start = admissible or (lambda _rid: True)
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
    counted = sum(x.state in ("warm", "booting") for x in nodes)
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
