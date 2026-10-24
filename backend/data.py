"""Deterministic, explicitly synthetic inputs for the GridShift demo."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

HOURS = tuple(range(24))
SEED = 2026

PRICE = [
    0.17, 0.16, 0.15, 0.14, 0.14, 0.15, 0.18, 0.21,
    0.24, 0.25, 0.22, 0.18, 0.16, 0.15, 0.15, 0.17,
    0.22, 0.29, 0.34, 0.32, 0.27, 0.23, 0.21, 0.19,
]
CARBON_INTENSITY = [
    0.55, 0.54, 0.53, 0.52, 0.51, 0.50, 0.48, 0.46,
    0.43, 0.40, 0.36, 0.33, 0.31, 0.30, 0.31, 0.34,
    0.40, 0.48, 0.55, 0.57, 0.58, 0.57, 0.56, 0.55,
]
RENEWABLE_AVAILABLE = [
    0, 0, 0, 0, 0, 0, 2, 8, 18, 32, 48, 62,
    72, 76, 70, 56, 38, 20, 8, 2, 0, 0, 0, 0,
]
REALTIME_GPUS = [
    40, 38, 36, 35, 36, 40, 48, 58, 66, 72, 75, 74,
    72, 70, 68, 72, 82, 88, 86, 78, 68, 58, 50, 44,
]
JOBS = [
    {"id": "train-a", "name": "Training run A", "arrival": 0, "deadline": 16, "gpu_hours": 480, "max_gpus": 80, "tier": "pro"},
    {"id": "train-b", "name": "Training run B", "arrival": 2, "deadline": 18, "gpu_hours": 540, "max_gpus": 90, "tier": "standard"},
    {"id": "batch-a", "name": "Batch inference A", "arrival": 5, "deadline": 21, "gpu_hours": 600, "max_gpus": 100, "tier": "pro"},
    {"id": "train-c", "name": "Training run C", "arrival": 8, "deadline": 24, "gpu_hours": 540, "max_gpus": 90, "tier": "standard"},
    {"id": "batch-b", "name": "Batch inference B", "arrival": 10, "deadline": 24, "gpu_hours": 480, "max_gpus": 80, "tier": "standard"},
    {"id": "train-d", "name": "Training run D", "arrival": 12, "deadline": 24, "gpu_hours": 420, "max_gpus": 70, "tier": "standard"},
]

TIERS = {"pro", "standard"}

SCENARIOS = {
    "baseline": {"label": "Balanced day", "description": "A full synthetic day with a midday renewable peak."},
    "price-spike": {"label": "Evening price spike", "description": "Grid price rises in the evening peak."},
    "renewables-shortage": {"label": "Renewables shortage", "description": "Midday renewable availability is reduced."},
    "demand-surge": {"label": "Demand surge", "description": "More real-time demand and flexible work stress capacity."},
}


def _number(value: Any, field: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.") from None
    if not math.isfinite(number) or number < low or number > high:
        raise ValueError(f"{field} must be between {low:g} and {high:g}.")
    return number


def _integer(value: Any, field: str, low: int, high: int) -> int:
    number = _number(value, field, low, high)
    if not number.is_integer():
        raise ValueError(f"{field} must be a whole number.")
    return int(number)


def build_case(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build and validate a deterministic case from user-facing controls."""
    payload = payload or {}
    scenario_id = payload.get("scenario", "baseline")
    if scenario_id not in SCENARIOS:
        raise ValueError("Choose one of the available scenarios.")

    gpu_count = _integer(payload.get("gpu_count", 256), "Total GPUs", 1, 512)
    carbon_weight = _number(payload.get("carbon_weight", 0.35), "Carbon weight", 0, 0.8)
    renewable_scale = _number(payload.get("renewable_scale", 1), "Renewable scale", 0, 1.5)
    demand_scale = _number(payload.get("demand_scale", 1), "Flexible-work scale", 0.5, 2.5)
    active_equivalent_fraction = _number(
        payload.get("realtime_active_equivalent_fraction", 1),
        "Active-equivalent real-time GPU fraction", 0, 1,
    )
    priority_policy = payload.get("priority_policy", "pro_priority")
    if not isinstance(priority_policy, str) or priority_policy not in {"pro_priority", "energy_only"}:
        raise ValueError("Priority policy must be Pro-priority or energy-only.")

    prices = list(PRICE)
    carbon = list(CARBON_INTENSITY)
    renewable = [value * renewable_scale for value in RENEWABLE_AVAILABLE]
    realtime = list(REALTIME_GPUS)
    jobs = deepcopy(JOBS)

    requested_tiers = payload.get("job_tiers", {})
    if requested_tiers is None:
        requested_tiers = {}
    if not isinstance(requested_tiers, dict):
        raise ValueError("Flexible-job tiers must be an object keyed by job ID.")
    known_job_ids = {job["id"] for job in jobs}
    if any(job_id not in known_job_ids for job_id in requested_tiers):
        raise ValueError("Flexible-job tiers contain an unknown job ID.")
    for job in jobs:
        tier = requested_tiers.get(job["id"], job["tier"])
        if not isinstance(tier, str) or tier.lower() not in TIERS:
            raise ValueError(f"Tier for {job['name']} must be Pro or Standard.")
        job["tier"] = tier.lower()

    if scenario_id == "price-spike":
        for hour in range(17, 21):
            prices[hour] *= 1.75
    elif scenario_id == "renewables-shortage":
        for hour in range(10, 16):
            renewable[hour] *= 0.25
    elif scenario_id == "demand-surge":
        realtime = [value + 12 for value in realtime]
        demand_scale *= 1.8

    for job in jobs:
        job["gpu_hours"] = round(job["gpu_hours"] * demand_scale, 6)

    hours = 1.0
    if gpu_count < max(realtime):
        raise ValueError(
            f"Total GPUs ({gpu_count}) must cover the maximum reserved real-time demand ({max(realtime)} GPUs)."
        )

    return {
        "scenario": scenario_id,
        "scenario_label": SCENARIOS[scenario_id]["label"],
        "scenario_description": SCENARIOS[scenario_id]["description"],
        "seed": SEED,
        "hours": list(HOURS),
        "slot_hours": hours,
        "gpu_count": gpu_count,
        "carbon_weight": carbon_weight,
        "renewable_scale": renewable_scale,
        "demand_scale": demand_scale,
        "realtime_active_equivalent_fraction": active_equivalent_fraction,
        "priority_policy": priority_policy,
        "price_cost_units_per_kwh": prices,
        "grid_carbon_kg_per_kwh": carbon,
        "renewable_available_kwh": renewable,
        "realtime_gpus": realtime,
        "active_equivalent_realtime_gpus": [value * active_equivalent_fraction for value in realtime],
        "power_assumptions": {
            "data_status": "synthetic_assumptions_not_measurements",
            "scenario": scenario_id,
            "seed": SEED,
            "base_it_kw": 18.0,
            "gpu_incremental_kw": 0.42,
            "pue": 1.25,
            "active_equivalent_fraction": active_equivalent_fraction,
            "active_equivalent_default_rule": "equals reserved real-time GPUs when fraction is 1.0",
        },
        "base_it_kw": 18.0,
        "gpu_incremental_kw": 0.42,
        "pue": 1.25,
        "jobs": jobs,
    }


def validate_case(case: dict[str, Any]) -> None:
    """Reject malformed inputs before calling the optimizer."""
    if case["slot_hours"] <= 0 or case["pue"] < 1:
        raise ValueError("Time-slot duration must be positive and PUE must be at least 1.")
    for field in ("price_cost_units_per_kwh", "grid_carbon_kg_per_kwh", "renewable_available_kwh", "realtime_gpus"):
        if len(case[field]) != 24:
            raise ValueError(f"{field} must contain 24 hourly values.")
    active_equivalent = case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])
    if len(active_equivalent) != 24 or any(
        not math.isfinite(active) or active < 0 or active > reserved
        for active, reserved in zip(active_equivalent, case["realtime_gpus"])
    ):
        raise ValueError("Active-equivalent real-time GPUs must be 24 values between zero and each hour's reserved GPU count.")
    if any(value < 0 for value in case["price_cost_units_per_kwh"]):
        raise ValueError("Synthetic grid prices must be nonnegative.")
    if any(value < 0 for value in case["grid_carbon_kg_per_kwh"] + case["renewable_available_kwh"]):
        raise ValueError("Carbon intensity and renewable availability must be nonnegative.")
    for job in case["jobs"]:
        if not 0 <= job["arrival"] < job["deadline"] <= 24:
            raise ValueError(f"Job {job['id']} must have 0 <= arrival < deadline <= 24.")
        if job["gpu_hours"] < 0 or job["max_gpus"] < 0:
            raise ValueError(f"Job {job['id']} demand and parallelism must be nonnegative.")
        if job.get("tier", "standard") not in TIERS:
            raise ValueError(f"Job {job['id']} tier must be Pro or Standard.")
