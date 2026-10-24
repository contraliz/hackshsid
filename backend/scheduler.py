"""Shared schedule evaluation, ASAP baseline, and HiGHS-backed LP optimizer."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.optimize import linprog

from .data import build_case, validate_case

TOLERANCE = 1e-6


def _hourly_load(case: dict[str, Any], flexible_gpu_hours: list[float]) -> list[float]:
    return [
        case["pue"]
        * (
            case["base_it_kw"] * case["slot_hours"]
            + case["gpu_incremental_kw"]
            * (case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])[hour] * case["slot_hours"] + flexible_gpu_hours[hour])
        )
        for hour in range(24)
    ]


def evaluate_schedule(case: dict[str, Any], schedule: list[list[float]]) -> dict[str, Any]:
    """Use one energy/cost/emissions accounting path for every method."""
    hours_per_slot = case["slot_hours"]
    flexible = [sum(schedule[j][hour] for j in range(len(case["jobs"]))) for hour in range(24)]
    load = _hourly_load(case, flexible)
    renewable_used = [min(load[hour], case["renewable_available_kwh"][hour]) for hour in range(24)]
    grid = [max(0.0, load[hour] - renewable_used[hour]) for hour in range(24)]
    curtailment = [max(0.0, case["renewable_available_kwh"][hour] - renewable_used[hour]) for hour in range(24)]
    gpu_use = [case["realtime_gpus"][hour] + flexible[hour] / hours_per_slot for hour in range(24)]

    job_results = []
    delivered_total = 0.0
    unmet_total = 0.0
    for index, job in enumerate(case["jobs"]):
        delivered = sum(schedule[index])
        unmet = max(0.0, job["gpu_hours"] - delivered)
        delivered_total += delivered
        unmet_total += unmet
        job_results.append({
            "id": job["id"], "name": job["name"], "demand_gpu_hours": job["gpu_hours"],
            "tier": job.get("tier", "standard"),
            "delivered_gpu_hours": delivered, "unmet_gpu_hours": unmet,
            "deadline_met": unmet <= TOLERANCE,
            "first_execution_hour": next((hour for hour, amount in enumerate(schedule[index]) if amount > TOLERANCE), None),
            "average_execution_hour": (
                sum(hour * amount for hour, amount in enumerate(schedule[index])) / delivered
                if delivered > TOLERANCE else None
            ),
        })

    cost = sum(case["price_cost_units_per_kwh"][hour] * grid[hour] for hour in range(24))
    emissions = sum(case["grid_carbon_kg_per_kwh"][hour] * grid[hour] for hour in range(24))
    weighted_objective = cost + case["carbon_weight"] * emissions
    completed = all(item["deadline_met"] for item in job_results)
    metrics = {
        "grid_cost_units": cost,
        "grid_emissions_kg_co2e": emissions,
        "renewable_used_kwh": sum(renewable_used),
        "renewable_curtailed_kwh": sum(curtailment),
        "grid_import_kwh": sum(grid),
        "load_kwh": sum(load),
        "flexible_gpu_hours_delivered": delivered_total,
        "flexible_gpu_hours_unmet": unmet_total,
        "deadlines_met": sum(1 for item in job_results if item["deadline_met"]),
        "deadline_count": len(job_results),
        "all_deadlines_met": completed,
        "peak_gpu_utilization": max(gpu_use),
        "peak_gpu_utilization_pct": max(gpu_use) / case["gpu_count"] * 100,
        "peak_reserved_gpu_utilization": max(case["realtime_gpus"][hour] + flexible[hour] / hours_per_slot for hour in range(24)),
        "installed_gpu_capacity": case["gpu_count"],
        "total_facility_energy_kwh": sum(load),
        "grid_import_kwh": sum(grid),
        "active_equivalent_realtime_gpu_hours": sum(case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])) * hours_per_slot,
        "reserved_realtime_gpu_hours": sum(case["realtime_gpus"]) * hours_per_slot,
        "peak_active_equivalent_gpu_power_use": max(
            case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])[hour] + flexible[hour] / hours_per_slot
            for hour in range(24)
        ),
        "weighted_objective_units": weighted_objective,
    }
    return {
        "metrics": metrics,
        "jobs": job_results,
        "hourly": {
            "flexible_gpu_hours": flexible,
            "realtime_gpus": list(case["realtime_gpus"]),
            "active_equivalent_realtime_gpus": list(case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])),
            "total_gpus": gpu_use,
            "load_kwh": load,
            "renewable_used_kwh": renewable_used,
            "renewable_available_kwh": list(case["renewable_available_kwh"]),
            "renewable_curtailed_kwh": curtailment,
            "grid_import_kwh": grid,
            "grid_price_cost_units_per_kwh": list(case["price_cost_units_per_kwh"]),
            "grid_carbon_kg_per_kwh": list(case["grid_carbon_kg_per_kwh"]),
        },
    }


def asap_baseline(case: dict[str, Any]) -> tuple[list[list[float]], str]:
    """Pro-tier-first, earliest-available baseline without price/carbon lookahead."""
    schedule = [[0.0 for _ in range(24)] for _ in case["jobs"]]
    capacity_used = [0.0] * 24
    for index, job in sorted(
        enumerate(case["jobs"]),
        key=lambda item: (0 if item[1].get("tier", "standard") == "pro" else 1, item[1]["arrival"], item[0]),
    ):
        remaining = float(job["gpu_hours"])
        for hour in range(job["arrival"], job["deadline"]):
            available = max(
                0.0,
                (case["gpu_count"] - case["realtime_gpus"][hour]) * case["slot_hours"] - capacity_used[hour],
            )
            amount = min(remaining, job["max_gpus"] * case["slot_hours"], available)
            if amount > TOLERANCE:
                schedule[index][hour] += amount
                capacity_used[hour] += amount
                remaining -= amount
            if remaining <= TOLERANCE:
                break
    status = "Complete" if all(
        sum(schedule[index]) >= job["gpu_hours"] - TOLERANCE
        for index, job in enumerate(case["jobs"])
    ) else "Missed deadlines"
    return schedule, status


def _independent_validation(case: dict[str, Any], schedule: list[list[float]], evaluation: dict[str, Any]) -> dict[str, float]:
    max_gpu_excess = 0.0
    max_parallel_excess = 0.0
    max_window_violation = 0.0
    max_completion_error = 0.0
    for index, job in enumerate(case["jobs"]):
        delivered = 0.0
        for hour, amount in enumerate(schedule[index]):
            if hour < job["arrival"] or hour >= job["deadline"]:
                max_window_violation = max(max_window_violation, abs(amount))
            delivered += amount
            max_parallel_excess = max(max_parallel_excess, amount - job["max_gpus"] * case["slot_hours"])
        max_completion_error = max(max_completion_error, abs(delivered - job["gpu_hours"]))
    for hour, total_gpu in enumerate(evaluation["hourly"]["total_gpus"]):
        max_gpu_excess = max(max_gpu_excess, total_gpu - case["gpu_count"])
    residuals = {
        "max_gpu_excess": max(0.0, max_gpu_excess),
        "max_job_parallel_excess_gpu_hours": max(0.0, max_parallel_excess),
        "max_release_deadline_violation_gpu_hours": max_window_violation,
        "max_job_completion_error_gpu_hours": max_completion_error,
    }
    return residuals


def solve_lp(case: dict[str, Any], priority_policy: str | None = None) -> dict[str, Any]:
    """Solve either the existing Pro-earliness policy or the energy-only diagnostic."""
    validate_case(case)
    priority_policy = priority_policy or case.get("priority_policy", "pro_priority")
    if priority_policy not in {"pro_priority", "energy_only"}:
        raise ValueError("Priority policy must be Pro-priority or energy-only.")
    job_count = len(case["jobs"])
    hours_count = 24
    x_count = job_count * hours_count
    grid_start = x_count
    renewable_start = grid_start + hours_count
    variable_count = renewable_start + hours_count

    def x_index(job_index: int, hour: int) -> int:
        return job_index * hours_count + hour

    objective = np.zeros(variable_count)
    for hour in range(24):
        objective[grid_start + hour] = (
            case["price_cost_units_per_kwh"][hour]
            + case["carbon_weight"] * case["grid_carbon_kg_per_kwh"][hour]
        )

    a_eq = []
    b_eq = []
    for job_index, job in enumerate(case["jobs"]):
        row = np.zeros(variable_count)
        for hour in range(job["arrival"], job["deadline"]):
            row[x_index(job_index, hour)] = 1.0
        a_eq.append(row)
        b_eq.append(job["gpu_hours"])

    for hour in range(24):
        row = np.zeros(variable_count)
        for job_index in range(job_count):
            row[x_index(job_index, hour)] = -case["pue"] * case["gpu_incremental_kw"]
        row[grid_start + hour] = 1.0
        row[renewable_start + hour] = 1.0
        a_eq.append(row)
        fixed_load = case["pue"] * (
            case["base_it_kw"] * case["slot_hours"]
            + case["gpu_incremental_kw"]
            * case.get("active_equivalent_realtime_gpus", case["realtime_gpus"])[hour]
            * case["slot_hours"]
        )
        b_eq.append(fixed_load)

    a_ub = []
    b_ub = []
    for hour in range(24):
        row = np.zeros(variable_count)
        for job_index in range(job_count):
            row[x_index(job_index, hour)] = 1.0
        a_ub.append(row)
        b_ub.append((case["gpu_count"] - case["realtime_gpus"][hour]) * case["slot_hours"])

    bounds: list[tuple[float, float | None]] = [(0.0, 0.0)] * x_count
    for job_index, job in enumerate(case["jobs"]):
        for hour in range(job["arrival"], job["deadline"]):
            bounds[x_index(job_index, hour)] = (0.0, job["max_gpus"] * case["slot_hours"])
    bounds.extend((0.0, None) for _ in range(hours_count))
    bounds.extend((0.0, case["renewable_available_kwh"][hour]) for hour in range(hours_count))

    status_names = {0: "Optimal", 1: "Iteration limit", 2: "Infeasible", 3: "Unbounded", 4: "Solver error"}
    base_a_ub = np.asarray(a_ub)
    base_b_ub = np.asarray(b_ub)
    a_eq_array = np.asarray(a_eq)
    b_eq_array = np.asarray(b_eq)
    priority_jobs = [
        index for index, job in sorted(
            enumerate(case["jobs"]), key=lambda pair: (pair[1]["arrival"], pair[0])
        ) if priority_policy == "pro_priority" and job.get("tier", "standard") == "pro"
    ]
    priority_constraints: list[np.ndarray] = []
    priority_bounds: list[float] = []
    priority_stages = []
    total_solve_time = 0.0
    total_iterations = 0

    def solve_stage(stage_objective: np.ndarray):
        nonlocal total_solve_time, total_iterations
        all_a_ub = np.vstack([base_a_ub, *priority_constraints]) if priority_constraints else base_a_ub
        all_b_ub = np.concatenate([base_b_ub, np.asarray(priority_bounds)]) if priority_bounds else base_b_ub
        started = time.perf_counter()
        stage_result = linprog(
            stage_objective,
            A_ub=all_a_ub,
            b_ub=all_b_ub,
            A_eq=a_eq_array,
            b_eq=b_eq_array,
            bounds=bounds,
            method="highs",
        )
        total_solve_time += time.perf_counter() - started
        total_iterations += int(getattr(stage_result, "nit", 0) or 0)
        return stage_result

    stage_error = None
    for priority_rank, job_index in enumerate(priority_jobs, start=1):
        earliness_objective = np.zeros(variable_count)
        for hour in range(case["jobs"][job_index]["arrival"], case["jobs"][job_index]["deadline"]):
            earliness_objective[x_index(job_index, hour)] = float(hour)
        result = solve_stage(earliness_objective)
        stage_status = status_names.get(result.status, "Solver error")
        if not result.success or result.status != 0:
            stage_error = (stage_status, str(result.message))
            priority_stages.append({
                "rank": priority_rank,
                "job_id": case["jobs"][job_index]["id"],
                "objective_value_gpu_hour_hours": None,
                "status": stage_status,
            })
            break
        optimum = float(np.dot(earliness_objective, result.x))
        allowed_error = max(1e-7, abs(optimum) * 1e-8)
        priority_constraints.extend([earliness_objective.copy(), -earliness_objective.copy()])
        priority_bounds.extend([optimum + allowed_error, -optimum + allowed_error])
        priority_stages.append({
            "rank": priority_rank,
            "job_id": case["jobs"][job_index]["id"],
            "objective_value_gpu_hour_hours": optimum,
            "preservation_tolerance_gpu_hour_hours": allowed_error,
            "status": "Optimal",
        })

    if stage_error:
        status, message = stage_error
        return {
            "status": status,
            "solver": "SciPy linprog / HiGHS (lexicographic Pro priority)" if priority_policy == "pro_priority" else "SciPy linprog / HiGHS (energy-only)",
            "success": False,
            "solve_time_seconds": total_solve_time,
            "iterations": total_iterations,
            "message": message,
            "tolerance": TOLERANCE,
            "priority_stages": priority_stages,
        }

    result = solve_stage(objective)
    status = status_names.get(result.status, "Solver error")
    optimized: dict[str, Any] = {
        "status": status,
        "solver": "SciPy linprog / HiGHS (lexicographic Pro priority)" if priority_policy == "pro_priority" else "SciPy linprog / HiGHS (energy-only)",
        "priority_policy": priority_policy,
        "priority_policy_label": "Pro-priority" if priority_policy == "pro_priority" else "Energy-only",
        "success": bool(result.success and result.status == 0),
        "solve_time_seconds": total_solve_time,
        "message": str(result.message),
        "iterations": total_iterations,
        "tolerance": TOLERANCE,
        "priority_stages": priority_stages,
        "policy_description": "Pro jobs are ordered by arrival then input order; each job's GPU-hour-weighted execution time is minimized before cost plus carbon. Standard work and all deadlines remain hard constraints." if priority_policy == "pro_priority" else "Minimize grid cost plus weighted grid emissions; all jobs retain the same hard completion, capacity, and deadline constraints.",
    }
    if not optimized["success"]:
        return optimized

    vector = np.asarray(result.x)
    schedule = [[float(vector[x_index(j, h)]) for h in range(24)] for j in range(job_count)]
    evaluated = evaluate_schedule(case, schedule)
    residuals = _independent_validation(case, schedule, evaluated)
    priority_errors = []
    for stage, job_index in zip(priority_stages, priority_jobs):
        measured = sum(hour * schedule[job_index][hour] for hour in range(24))
        priority_errors.append(abs(measured - stage["objective_value_gpu_hour_hours"]))
    residuals["max_priority_earliness_deviation_gpu_hour_hours"] = max(priority_errors, default=0.0)
    hard_residuals = {
        key: value for key, value in residuals.items()
        if key != "max_priority_earliness_deviation_gpu_hour_hours"
    }
    priority_passed = all(
        error <= stage.get("preservation_tolerance_gpu_hour_hours", 0.0) + 1e-10
        for error, stage in zip(priority_errors, priority_stages)
    )
    if max(hard_residuals.values(), default=0.0) > TOLERANCE or not priority_passed:
        return {
            **optimized,
            "status": "Solver validation failed",
            "success": False,
            "validation": {"passed": False, "residuals": residuals},
        }

    objective_error = abs(float(result.fun) - evaluated["metrics"]["weighted_objective_units"])
    if objective_error > max(TOLERANCE, TOLERANCE * abs(float(result.fun))):
        return {
            **optimized,
            "status": "Objective validation failed",
            "success": False,
            "validation": {"passed": False, "residuals": residuals, "objective_error_units": objective_error},
        }

    optimized.update({
        "schedule_gpu_hours": schedule,
        "metrics": evaluated["metrics"],
        "jobs": evaluated["jobs"],
        "hourly": evaluated["hourly"],
        "objective_value_units": float(result.fun),
        "validation": {"passed": True, "residuals": residuals, "objective_error_units": objective_error},
    })
    return optimized


def run_comparison(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    case = build_case(payload)
    validate_case(case)
    baseline_schedule, baseline_status = asap_baseline(case)
    baseline_eval = evaluate_schedule(case, baseline_schedule)
    selected_policy = case["priority_policy"]
    optimizer = solve_lp(case, selected_policy)
    alternate_policy = "energy_only" if selected_policy == "pro_priority" else "pro_priority"
    alternate_optimizer = solve_lp(case, alternate_policy)

    comparison: dict[str, Any] = {"cost_savings_pct": None, "emissions_change_pct": None, "comparable": False}
    optimized_result = None
    if optimizer.get("success"):
        optimized_result = evaluate_schedule(case, optimizer["schedule_gpu_hours"])
        baseline_metrics = baseline_eval["metrics"]
        optimized_metrics = optimized_result["metrics"]
        comparison["comparable"] = baseline_metrics["all_deadlines_met"] and optimized_metrics["all_deadlines_met"]
        if comparison["comparable"]:
            if baseline_metrics["grid_cost_units"] != 0:
                comparison["cost_savings_pct"] = (
                    (baseline_metrics["grid_cost_units"] - optimized_metrics["grid_cost_units"])
                    / baseline_metrics["grid_cost_units"] * 100
                )
            if baseline_metrics["grid_emissions_kg_co2e"] != 0:
                comparison["emissions_change_pct"] = (
                    (baseline_metrics["grid_emissions_kg_co2e"] - optimized_metrics["grid_emissions_kg_co2e"])
                    / baseline_metrics["grid_emissions_kg_co2e"] * 100
                )

    policy_diagnostic = {}
    for policy, candidate in ((selected_policy, optimizer), (alternate_policy, alternate_optimizer)):
        policy_diagnostic[policy] = {
            "status": candidate["status"],
            "success": candidate["success"],
            "metrics": candidate.get("metrics"),
            "jobs": candidate.get("jobs"),
            "policy_label": candidate.get("priority_policy_label", "Pro-priority" if policy == "pro_priority" else "Energy-only"),
        }

    return {
        "case": {
            key: value for key, value in case.items()
            if key not in {"jobs"}
        } | {"jobs": case["jobs"]},
        "baseline": {
            "status": baseline_status,
            "schedule_gpu_hours": baseline_schedule,
            **baseline_eval,
        },
        "optimizer": optimizer,
        "optimized": optimized_result,
        "comparison": comparison,
        "policy_diagnostic": {
            "same_input": True,
            "selected_policy": selected_policy,
            "selected_policy_label": "Pro-priority" if selected_policy == "pro_priority" else "Energy-only",
            "policies": policy_diagnostic,
        },
        "model": {
            "objective": "Selected policy: " + ("lexicographically minimize Pro GPU-hour-weighted execution time, then minimize grid cost + carbon weight × operational grid emissions" if selected_policy == "pro_priority" else "minimize grid cost + carbon weight × operational grid emissions"),
            "time_step_hours": case["slot_hours"],
            "flexible_work": "divisible and preemptible; fractional GPU-hours allowed",
            "real_time_work": "exogenous reserved GPU demand; no request-level latency model",
            "optimality_scope": "optimal for the selected LP policy and these synthetic inputs; all job completion, capacity, and deadline constraints stay hard constraints",
            "baseline_policy": "Priority-aware arrival-order ASAP: Pro jobs first, FIFO within tier; same shared evaluator",
            "priority_epsilon": "each Pro earliness optimum is preserved within max(1e-7, 1e-8 × absolute optimum) GPU-hour-hours before the next pass" if selected_policy == "pro_priority" else None,
            "power_assumptions": case["power_assumptions"],
            "capacity_uses_reserved_realtime_gpus": True,
            "energy_uses_active_equivalent_realtime_gpus": True,
        },
    }
