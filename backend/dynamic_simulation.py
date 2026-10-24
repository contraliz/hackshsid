"""Minute-resolution, reproducible node-state simulation for synthetic requests.

This is a comparison model, not a controller. Traffic, power coefficients and
forecast calibration are synthetic scenario assumptions.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import random
from typing import Any

from .data import RENEWABLE_AVAILABLE

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
    requests = generate_requests(seed, burst=bool(payload.get("bursts", True)))
    offered = _offered_gpu_trace(requests)
    # Current day is used to form the diagnostic forecast; actions at bucket b
    # see only maxima from buckets strictly before b.
    _, forecast_b = _forecast_series(offered, alpha)
    # No independent historical error archive exists yet. The explicitly
    # uncalibrated fallback is calculated from the forecast at each decision,
    # never from the current day's later realized demand.
    policies = {name: _run_policy(requests, offered, forecast_b, n, gpn, seed, margin_fraction, min_active_nodes, name)
                for name in ("always_on", "reactive", "forecast")}
    return {
        "seed": seed, "nodes": n, "gpus_per_node": gpn, "fleet_gpus": n * gpn,
        "requests_generated": len(requests), "offered_peak_gpus": max(offered, default=0),
        "forecast_margin_rule": f"max(4 GPUs, {margin_fraction:.0%} of the current causal forecast)", "selected_policy": "forecast",
        "forecast_alpha": alpha, "margin_fraction": margin_fraction,
        "minimum_active_nodes": min_active_nodes,
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
            "flexible_jobs": "This new minute simulation models generated requests only; flexible-job LP remains the existing separate 24-hour prototype. No flexible work is dropped or claimed completed by this comparison.",
        },
    }


def _run_policy(requests, offered, forecast_b, n, gpn, seed, margin_fraction, min_active_nodes, policy):
    nodes = [Node("active" if policy == "always_on" else "active" if i < max(2, n // 2) else "warm" if i < max(2, n // 2) + 2 else "off") for i in range(n)]
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
    forecast_idx = 0
    for minute in range(MINUTES_PER_DAY):
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
                target_warm = min(n - sum(x.state == "active" for x in nodes),
                                  math.ceil(max(0, upper - active_capacity) / gpn))
                _ensure_warm_reserve(nodes, target_warm)
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
            required = math.ceil((sum(r["gpus"] for r in running.values()) + sum(statuses[r]["gpus"] for r in waiting)) / gpn)
            _scale_up(nodes, min(n, required), gpn)
        # Serve interactive before batch; 15-minute aging protects batch starts.
        while waiting:
            free = [(ni, gpn - node.used) for ni, node in enumerate(nodes) if node.state == "active"]
            free_gpu = sum(x for _, x in free)
            if not free_gpu:
                break
            rid = _choose_waiting_request(waiting, statuses, minute, free_gpu)
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
            active_demand = sum(r["gpus"] for r in running.values()) + sum(statuses[r]["gpus"] for r in waiting)
            minimum_active = max(min_active_nodes, math.ceil(active_demand / gpn))
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
        it_kw = 18.0 + active * 1.0 + warm * 0.25 + boot * 1.2 + busy_gpus * 0.35
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
            shortfall = max(0.0, upper - n * gpn)
            timeline_states.append({"minute": minute, "offered_gpus": offered[minute], "forecast_gpus": round(forecast, 2), "forecast_upper_gpus": round(upper, 2), "forecast_capacity_shortfall_gpus": round(max(0, upper - n * gpn), 2), "target_warm_nodes": target_warm, "running_gpus": busy_gpus,
                                    "queued_requests": len(waiting), "active_capacity_gpus": active * gpn, "ready_in_5m_capacity_gpus": (active + warm) * gpn, "active_nodes": active, "warm_nodes": warm,
                                    "booting_nodes": boot, "off_nodes": n-active-warm-boot})
    counts = {state: sum(v["status"] == state for v in statuses.values()) for state in ("completed", "queued", "running", "rejected")}
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
        "peak_active_nodes": max((x["active_nodes"] for x in timeline_states), default=0),
        "peak_offered_gpu_demand": max(offered, default=0),
        "max_forecast_capacity_shortfall_gpus": max((x["forecast_capacity_shortfall_gpus"] for x in timeline_states), default=0),
        "forecast_shortfall_minutes": sum(5 for x in timeline_states if x["forecast_capacity_shortfall_gpus"] > 0),
        "peak_offered_fleet_shortfall_gpus": max((max(0, d - n * gpn) for d in offered), default=0),
        "offered_fleet_shortfall_minutes": sum(d > n * gpn for d in offered),
        "active_capacity_shortfall_gpu_minutes": sum(max(0, offered[row["minute"]] - row["active_nodes"] * gpn) * 5 for row in timeline_states),
    }
    return {"label": policy.replace("_", " ").title(), "metrics": metrics, "state_trace": timeline_states,
            "request_status_counts": counts}


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


def _choose_waiting_request(waiting: deque[str], statuses: dict[str, dict[str, Any]], minute: int, free_gpus: int) -> str | None:
    aged_batch = sorted((rid for rid in waiting if statuses[rid]["class"] == "batch"
                         and minute - statuses[rid]["arrival"] >= 15),
                        key=lambda rid: (statuses[rid]["arrival"], rid))
    if aged_batch:
        # Protect the oldest aged batch request from being perpetually
        # backfilled by newer arrivals while it waits for enough free GPUs.
        head = aged_batch[0]
        return head if statuses[head]["gpus"] <= free_gpus else None
    candidates = sorted(waiting, key=lambda rid: (
        0 if statuses[rid]["class"] == "interactive" else 1,
        statuses[rid]["arrival"], rid,
    ))
    return next((rid for rid in candidates if statuses[rid]["gpus"] <= free_gpus), None)


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
