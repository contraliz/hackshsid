#!/usr/bin/env python3
"""Run reproducible, synthetic batches against GridShift's real simulator."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.dynamic_simulation import generate_requests, run_dynamic_comparison


CONTROLLERS = ("always_on", "reactive", "forecast")
SCENARIOS = ("normal_day", "demand_burst", "constrained_fleet")
STATES = ("active", "warm", "warming", "booting", "off")
SERVICE_METRICS = (
    "requests_completed", "requests_rejected", "requests_queued_at_horizon",
    "requests_running_at_horizon", "mean_wait_minutes", "p95_wait_minutes",
    "mean_completion_latency_minutes", "latency_allowance_met", "latency_allowance_total",
    "flexible_jobs_admitted", "flexible_jobs_deadline_met", "flexible_gpu_hours_scheduled",
    "flexible_gpu_hours_delivered", "flexible_gpu_hours_unmet", "flexible_deadline_misses",
    "flexible_commitment_missed_gpu_minutes",
)
CANONICAL_PERCENT_KEYS = {
    "electricity": "electricity_pct",
    "grid_import": "grid_import_pct",
    "cost": "cost_pct",
    "emissions": "emissions_pct",
}
BASELINE_METRICS = (
    "facility_kwh", "grid_kwh", "renewable_used_kwh", "renewable_curtailed_kwh",
    "cost_cny", "emissions_kg", *SERVICE_METRICS,
)

METRIC_FIELDS = (
    "requests_generated", "requests_completed", "requests_queued_at_horizon",
    "requests_running_at_horizon", "requests_rejected", "completion_fraction",
    "mean_wait_minutes", "p95_wait_minutes", "mean_completion_latency_minutes",
    "latency_allowance_met", "latency_allowance_total", "offered_gpu_minutes",
    "served_gpu_minutes", "flexible_admission_status", "flexible_jobs_admitted",
    "flexible_jobs_deadline_met", "flexible_deadline_misses",
    "flexible_gpu_hours_scheduled", "flexible_gpu_hours_delivered",
    "flexible_gpu_hours_unmet", "flexible_commitment_missed_gpu_minutes",
    "facility_kwh", "grid_kwh", "renewable_used_kwh", "renewable_curtailed_kwh",
    "cost_cny", "emissions_kg", "peak_active_nodes", "peak_offered_gpu_demand",
    "max_forecast_capacity_shortfall_gpus", "forecast_shortfall_minutes",
    "peak_offered_fleet_shortfall_gpus", "offered_fleet_shortfall_minutes",
    "active_capacity_shortfall_gpu_minutes",
    *(f"state_{state}_node_minutes" for state in STATES),
    "state_transition_count",
)

CSV_FIELDS = (
    "scenario", "scenario_description", "seed", "record_kind", "controller", "controller_label", "status", "error",
    "objective_analysis_status", "objective_scope", "objective_candidate_status", "objective_service_eligible",
    "pareto_absolute_tolerance", "pareto_relative_tolerance",
    "pareto_frontier_candidate", "minimum_facility_kwh", "minimum_cost_cny", "minimum_emissions_kg",
    "nodes", "gpus_per_node", "fleet_gpus", "scenario_config_json", "assumptions_json",
    "selected_policy", "canonical_comparison_status", "comparison_baseline_label",
    "canonical_service_comparable", "canonical_service_note",
    "unscheduled_baseline_flexible_admission_status", "unscheduled_baseline_flexible_admission_reason",
    *[f"unscheduled_baseline_{field}" for field in BASELINE_METRICS],
    *[f"{metric}_savings_pct" for metric in CANONICAL_PERCENT_KEYS],
    *[f"{metric}_pct_reported" for metric in CANONICAL_PERCENT_KEYS],
    *[f"{metric}_savings_reason" for metric in CANONICAL_PERCENT_KEYS],
    "flexible_admission_status", "flexible_admission_reason",
    *[field for field in METRIC_FIELDS if field != "flexible_admission_status"],
    "cost_change_cny_vs_always_on", "cost_savings_pct_vs_always_on",
    "cost_comparison_note",
)


def build_scenario(name: str, seed: int, *, forecast_alpha: float = 0.3,
                   margin_fraction: float = 0.15,
                   min_active_fraction: float = 0.25) -> dict[str, Any]:
    """Materialize supported simulator inputs once per scenario and seed."""
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {name}")
    trace = generate_requests(seed, burst=False)
    nodes, gpus_per_node = 32, 8
    description = "Seeded normal one-day request trace; hidden burst generation disabled."
    config: dict[str, Any] = {
        "nodes": nodes,
        "gpus_per_node": gpus_per_node,
        "bursts": False,
        "request_trace_source": "backend.dynamic_simulation.generate_requests(seed, burst=False)",
    }

    if name == "demand_burst":
        burst = [{
            "id": f"experiment-burst-{index + 1:03d}", "class": "interactive",
            "arrival": 12 * 60, "gpus": 4, "duration": 2, "latency": 2,
        } for index in range(80)]
        trace = trace + burst
        description = "Normal seeded trace plus 80 simultaneous synthetic 4-GPU requests at minute 720 (320 offered GPUs)."
        config.update({"burst_request_count": 80, "burst_arrival_minute": 720,
                       "burst_gpus_per_request": 4, "burst_duration_minutes": 2,
                       "burst_total_gpus": 320, "request_count": len(trace)})
    elif name == "constrained_fleet":
        nodes, gpus_per_node = 2, 4
        trace = [{
            "id": f"fleet-overload-{index + 1:02d}", "class": "batch",
            "arrival": 0, "gpus": 8, "duration": 180, "latency": 30,
        } for index in range(16)]
        description = "Eight-GPU fleet with 16 simultaneous synthetic 8-GPU batch requests; flexible LP admission may be infeasible."
        config = {"nodes": nodes, "gpus_per_node": gpus_per_node,
                  "bursts": False, "request_trace_source": "fixed controlled overload trace",
                  "request_count": 16, "arrival_minute": 0, "gpus_per_request": 8,
                  "duration_minutes": 180}
    elif name == "normal_day":
        config["request_count"] = len(trace)

    config["nodes"] = nodes
    config["gpus_per_node"] = gpus_per_node
    config["forecast_alpha"] = forecast_alpha
    config["margin_fraction"] = margin_fraction
    config["min_active_fraction"] = min_active_fraction
    payload = {
        "seed": seed, "nodes": nodes, "gpus_per_node": gpus_per_node,
        "bursts": False, "request_trace": trace,
        "forecast_alpha": forecast_alpha, "margin_fraction": margin_fraction,
        "min_active_fraction": min_active_fraction,
    }
    return {"name": name, "description": description, "config": config, "payload": payload}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _state_summary(policy: dict[str, Any]) -> dict[str, int | None]:
    replay = policy.get("replay")
    frames = replay.get("frames") if isinstance(replay, dict) else None
    counts = {f"state_{state}_node_minutes": 0 for state in STATES}
    counts["state_transition_count"] = 0
    if not isinstance(frames, list) or not frames:
        return {key: None for key in counts}
    previous: list[Any] | None = None
    for frame in frames:
        states = frame.get("states") if isinstance(frame, dict) else None
        if not isinstance(states, list):
            return {key: None for key in counts}
        for state in states:
            key = f"state_{state}_node_minutes"
            if key in counts:
                counts[key] += 1
        if previous is not None and len(previous) == len(states):
            counts["state_transition_count"] += sum(a != b for a, b in zip(previous, states))
        previous = states
    return counts


def _flex_outcome(policy: dict[str, Any]) -> tuple[Any, ...] | None:
    jobs = policy.get("flexible_jobs")
    if not isinstance(jobs, list):
        return None
    result = []
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("id"), str):
            return None
        if (not isinstance(job.get("admitted"), bool)
                or not isinstance(job.get("deadline_met"), bool)
                or not _finite_number(job.get("delivered_gpu_hours"))
                or not _finite_number(job.get("unmet_gpu_hours"))):
            return None
        result.append((job["id"], job.get("admitted"), job.get("deadline_met"),
                       job.get("delivered_gpu_hours"), job.get("unmet_gpu_hours")))
    return tuple(sorted(result))


def same_service_outcome(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """Require the same completed request set and flexible-work outcome."""
    candidate_replay = candidate.get("replay")
    baseline_replay = baseline.get("replay")
    if not isinstance(candidate_replay, dict) or not isinstance(baseline_replay, dict):
        return False
    candidate_requests = candidate_replay.get("requests")
    baseline_requests = baseline_replay.get("requests")
    if not isinstance(candidate_requests, list) or not isinstance(baseline_requests, list):
        return False
    candidate_status = {item.get("id"): item.get("status") for item in candidate_requests if isinstance(item, dict)}
    baseline_status = {item.get("id"): item.get("status") for item in baseline_requests if isinstance(item, dict)}
    if len(candidate_status) != len(candidate_requests) or len(baseline_status) != len(baseline_requests):
        return False
    if candidate_status != baseline_status:
        return False
    candidate_flex, baseline_flex = _flex_outcome(candidate), _flex_outcome(baseline)
    if candidate_flex is None or baseline_flex is None or len(candidate_flex) != len(baseline_flex):
        return False
    for candidate_job, baseline_job in zip(candidate_flex, baseline_flex):
        if candidate_job[:3] != baseline_job[:3]:
            return False
        for candidate_value, baseline_value in zip(candidate_job[3:], baseline_job[3:]):
            if not _finite_number(candidate_value) or not _finite_number(baseline_value):
                if candidate_value != baseline_value:
                    return False
            elif not math.isclose(candidate_value, baseline_value, rel_tol=0, abs_tol=1e-6):
                return False
    return True


def cost_comparison(cost: Any, baseline_cost: Any, *, comparable: bool) -> tuple[float | None, float | None, str]:
    """Return avoided cost and percent only when service outcomes match."""
    if not comparable:
        return None, None, "Not compared: request or flexible-work outcomes differ or are unavailable."
    if not _finite_number(cost) or not _finite_number(baseline_cost):
        return None, None, "Not compared: cost metric is unavailable."
    difference = round(baseline_cost - cost, 3)
    if baseline_cost == 0:
        return difference, None, "Absolute difference shown; percentage unavailable because always-on cost is zero."
    return difference, round((difference / baseline_cost) * 100, 2), "Same request and flexible-work outcomes; latency metrics remain visible separately."


def _failed_row(scenario: dict[str, Any], seed: int, controller: str, error: str) -> dict[str, Any]:
    row = {field: None for field in CSV_FIELDS}
    row.update({"scenario": scenario["name"], "scenario_description": scenario["description"],
                "seed": seed, "controller": controller, "status": "failed", "error": error,
                "nodes": scenario["config"].get("nodes"),
                "gpus_per_node": scenario["config"].get("gpus_per_node"),
                "fleet_gpus": scenario["config"].get("nodes", 0) * scenario["config"].get("gpus_per_node", 0),
                "scenario_config_json": json.dumps(scenario["config"], sort_keys=True),
                "cost_comparison_note": "No comparison available for a failed run."})
    return row


def _metric_row(scenario: dict[str, Any], seed: int, result: dict[str, Any], *,
                record_kind: str, controller: str, label: str,
                metrics: dict[str, Any], policy: dict[str, Any] | None = None,
                flexible_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {field: None for field in CSV_FIELDS}
    row.update({
        "scenario": scenario["name"], "scenario_description": scenario["description"],
        "seed": seed, "record_kind": record_kind, "controller": controller,
        "controller_label": label, "status": "complete", "error": None,
        "nodes": result.get("nodes", scenario["config"].get("nodes")),
        "gpus_per_node": result.get("gpus_per_node", scenario["config"].get("gpus_per_node")),
        "fleet_gpus": result.get("fleet_gpus"),
        "scenario_config_json": json.dumps(scenario["config"], sort_keys=True),
        "assumptions_json": json.dumps(result.get("assumptions"), sort_keys=True),
        "selected_policy": result.get("selected_policy"),
        "flexible_admission_status": (policy or {}).get("flexible_admission_status")
        or (flexible_summary or {}).get("admission_status"),
        "flexible_admission_reason": (policy or {}).get("flexible_admission_reason")
        or (flexible_summary or {}).get("admission_reason"),
    })
    for field in METRIC_FIELDS:
        if field.startswith("state_") or field == "state_transition_count":
            continue
        if field == "requests_generated":
            value = result.get("requests_generated")
        elif field == "flexible_admission_status":
            value = row["flexible_admission_status"]
        else:
            value = metrics.get(field)
        if field == "flexible_admission_status":
            row[field] = value if isinstance(value, str) else None
        else:
            row[field] = value if value is None or _finite_number(value) else None
    if policy is not None:
        row.update(_state_summary(policy))
    return row


def _canonical_comparison_status(baseline: Any, comparison: Any, controller: str) -> str:
    if not isinstance(baseline, dict) or not isinstance(baseline.get("metrics"), dict):
        return "legacy_api_no_unscheduled_baseline"
    if not isinstance(comparison, dict):
        return "missing_controller_comparison"
    baseline_ref = comparison.get("baseline")
    optimized_ref = comparison.get("optimized")
    if (not isinstance(baseline_ref, dict) or not isinstance(baseline_ref.get("metrics"), dict)
            or not isinstance(optimized_ref, dict) or not isinstance(optimized_ref.get("metrics"), dict)
            or not isinstance(comparison.get("savings"), dict)
            or not isinstance(comparison.get("service_comparable"), bool)):
        return "incomplete_controller_comparison"
    if baseline_ref.get("key") != "unscheduled" or optimized_ref.get("key") != controller:
        return "incomplete_controller_comparison"
    return "available"


def _finite_or_none(value: Any) -> float | None:
    return float(value) if _finite_number(value) else None


def _attach_canonical_comparison(row: dict[str, Any], baseline: Any, comparison: Any,
                                 controller: str, objective_analysis: Any = None) -> None:
    status = _canonical_comparison_status(baseline, comparison, controller)
    row["canonical_comparison_status"] = status
    if status != "available":
        return
    base_ref = comparison["baseline"]
    row["comparison_baseline_label"] = base_ref.get("label") or baseline.get("label")
    for field in BASELINE_METRICS:
        row[f"unscheduled_baseline_{field}"] = _finite_or_none(base_ref["metrics"].get(field))
    row["unscheduled_baseline_flexible_admission_status"] = baseline.get("flexible_admission_status")
    row["unscheduled_baseline_flexible_admission_reason"] = baseline.get("flexible_admission_reason")
    row["canonical_service_comparable"] = comparison["service_comparable"]
    row["canonical_service_note"] = comparison.get("service_note")
    savings = comparison["savings"]
    for field, source_key in CANONICAL_PERCENT_KEYS.items():
        reported = _finite_or_none(savings.get(source_key))
        row[f"{field}_pct_reported"] = reported
        reasons = comparison.get("savings_reason")
        row[f"{field}_savings_reason"] = reasons.get(source_key) if isinstance(reasons, dict) else None
        # Keep the backend percentage for transparent analysis, but call it a
        # saving only when its canonical service-equivalence check passed.
        row[f"{field}_savings_pct"] = reported if comparison["service_comparable"] else None
    _attach_objective_candidate(row, objective_analysis, controller)


def _attach_objective_candidate(row: dict[str, Any], analysis: Any, candidate_key: str) -> None:
    if not isinstance(analysis, dict):
        row["objective_analysis_status"] = "unavailable"
        return
    row["objective_analysis_status"] = analysis.get("status")
    row["objective_scope"] = analysis.get("scope")
    tolerance = analysis.get("tolerance")
    if isinstance(tolerance, dict):
        row["pareto_absolute_tolerance"] = tolerance.get("absolute")
        row["pareto_relative_tolerance"] = tolerance.get("relative")
    candidates = analysis.get("candidates")
    candidate = candidates.get(candidate_key) if isinstance(candidates, dict) else None
    if not isinstance(candidate, dict):
        return
    row["objective_candidate_status"] = candidate.get("status")
    row["objective_service_eligible"] = candidate.get("service_eligible")
    row["pareto_frontier_candidate"] = candidate.get("pareto_frontier")
    minima = candidate.get("individual_minima")
    if isinstance(minima, dict):
        row["minimum_facility_kwh"] = minima.get("facility_kwh")
        row["minimum_cost_cny"] = minima.get("cost_cny")
        row["minimum_emissions_kg"] = minima.get("emissions_kg")


def run_batch(seeds: list[int], scenario_names: list[str], *, runner: Callable[[dict[str, Any]], dict[str, Any]] = run_dynamic_comparison,
              forecast_alpha: float = 0.3, margin_fraction: float = 0.15,
              min_active_fraction: float = 0.25) -> list[dict[str, Any]]:
    rows = []
    for seed in seeds:
        for scenario_name in scenario_names:
            scenario = build_scenario(scenario_name, seed, forecast_alpha=forecast_alpha,
                                      margin_fraction=margin_fraction,
                                      min_active_fraction=min_active_fraction)
            try:
                result = runner(scenario["payload"])
                if not isinstance(result, dict) or not isinstance(result.get("policies"), dict):
                    raise ValueError("Simulator response is missing its policies comparison object.")
            except Exception as error:  # Preserve a row for each failed controller/scenario.
                message = f"{type(error).__name__}: {error}"
                rows.extend(_failed_row(scenario, seed, controller, message) for controller in CONTROLLERS)
                continue

            policies = result["policies"]
            raw_policies = {name: policies.get(name) for name in CONTROLLERS}
            baseline = raw_policies.get("always_on")
            unscheduled = result.get("unscheduled_baseline")
            if isinstance(unscheduled, dict) and isinstance(unscheduled.get("metrics"), dict):
                baseline_row = _metric_row(
                    scenario, seed, result, record_kind="unscheduled_baseline",
                    controller="unscheduled_baseline",
                    label=str(unscheduled.get("label") or "Unscheduled baseline"),
                    metrics=unscheduled["metrics"], policy=unscheduled,
                    flexible_summary=unscheduled,
                )
                _attach_objective_candidate(baseline_row, result.get("objective_analysis"), "unscheduled")
                comparison_map = result.get("comparisons")
                if not isinstance(comparison_map, dict):
                    baseline_row["canonical_comparison_status"] = "missing_controller_comparison"
                else:
                    statuses = [_canonical_comparison_status(unscheduled, comparison_map.get(name), name)
                                for name in CONTROLLERS]
                    baseline_row["canonical_comparison_status"] = (
                        "available" if all(status == "available" for status in statuses)
                        else "incomplete_controller_comparison")
                rows.append(baseline_row)
            for controller in CONTROLLERS:
                policy = raw_policies.get(controller)
                if not isinstance(policy, dict) or not isinstance(policy.get("metrics"), dict):
                    rows.append(_failed_row(scenario, seed, controller,
                                            "ValueError: simulator response is missing controller metrics."))
                    continue
                metrics = policy["metrics"]
                row = _metric_row(
                    scenario, seed, result, record_kind="scheduled_policy",
                    controller=controller, label=str(policy.get("label") or controller),
                    metrics=metrics, policy=policy,
                    flexible_summary=result.get("flexible_schedule"),
                )
                comparison = result.get("comparisons", {}).get(controller) if isinstance(result.get("comparisons"), dict) else None
                _attach_canonical_comparison(row, unscheduled, comparison, controller,
                                             result.get("objective_analysis"))

                comparable = controller == "always_on" or (
                    isinstance(baseline, dict) and same_service_outcome(policy, baseline))
                delta, pct, note = cost_comparison(metrics.get("cost_cny"),
                                                   baseline.get("metrics", {}).get("cost_cny") if isinstance(baseline, dict) else None,
                                                   comparable=comparable)
                row["cost_change_cny_vs_always_on"] = delta
                row["cost_savings_pct_vs_always_on"] = pct
                row["cost_comparison_note"] = note
                rows.append(row)
    return rows


def write_outputs(rows: list[dict[str, Any]], output_dir: Path | str, *, seeds: list[int],
                  scenario_names: list[str]) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path, report_path = directory / "summary.csv", directory / "report.md"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# GridShift operational simulation experiment report", "",
        f"- Seeds: {', '.join(map(str, seeds))}",
        f"- Scenarios: {', '.join(scenario_names)}",
        "- Simulation status: synthetic and illustrative; these are not measured infrastructure results or service guarantees.",
        "- Controller comparisons come from one simulator invocation per seed/scenario, which evaluates all supported controllers against the same request trace and flexible schedule.",
        "- Canonical scheduled-versus-unscheduled percentages are taken from the simulator response. Formula: `(unscheduled baseline − scheduled result) / unscheduled baseline × 100`; negative values mean increases. Percent savings are shown only when the simulator says service outcomes are comparable.",
        "- The unscheduled baseline is all-nodes-active, immediate FIFO/ASAP work without energy scheduling. The existing `always_on` controller remains flexible-LP scheduled; it is not the unscheduled baseline.",
        "- Three-objective results are a Pareto frontier of the simulated same-trace candidates (facility kWh, grid cost CNY, operational grid kg CO₂), not a global optimizer. Only API-marked service-eligible candidates enter the frontier; no scalar weights are applied.",
        "- The older scheduled-controller cost diagnostic remains separately labeled; its percentage is shown only when request terminal statuses and flexible-work outcomes match. Latency metrics are shown separately.",
        "- Missing metrics are shown as unavailable (—), never as zero. Renewable inputs are the simulator's fixed synthetic profile; no renewable override is supported.", "",
    ]
    successful = next((row for row in rows if row.get("status") == "complete"), None)
    if successful:
        try:
            assumptions = json.loads(successful.get("assumptions_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            assumptions = {}
        if assumptions:
            lines.extend(["## Input provenance", "", f"- Data status: {assumptions.get('data_status', '—')}",
                          f"- Demand: {assumptions.get('demand_model', '—')}",
                          f"- IT power assumptions: `{json.dumps(assumptions.get('power_kw_it'), sort_keys=True)}`; PUE {assumptions.get('pue', '—')}.",
                          f"- Tariff: {assumptions.get('tariff', '—')} ([source]({assumptions.get('tariff_reference_url', '')})).",
                          f"- Grid carbon: {assumptions.get('grid_emissions', '—')} ([source]({assumptions.get('grid_emissions_reference_url', '')})).", ""])

    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row.get("scenario"), row.get("seed")), []).append(row)
    for (scenario_name, seed), group in grouped.items():
        desc = next((row.get("scenario_description") for row in group if row.get("scenario_description")), "")
        config = next((row.get("scenario_config_json") for row in group if row.get("scenario_config_json")), "{}")
        baseline_row = next((row for row in group if row.get("record_kind") == "unscheduled_baseline"), None)
        policy_rows = [row for row in group if row.get("record_kind") != "unscheduled_baseline"]
        lines.extend([f"## {scenario_name} · seed {seed}", "", desc, "", f"Configuration: `{config}`", ""])
        objective_status = next((row.get("objective_analysis_status") for row in group if row.get("objective_analysis_status")), None)
        objective_rows = [row for row in group if row.get("status") == "complete"]
        if objective_status:
            lines.extend(["### Three-objective candidate frontier", "",
                          "The simulator classifies service-eligible candidates by facility electricity, illustrative grid cost, and operational grid emissions together. An individual-minimum marker is per metric; a Pareto candidate is non-dominated among these simulated alternatives only. Tolerance is max(0.001 metric units, 1e-9 × max magnitude). Service eligibility means matching terminal/flexible outcomes, not meeting a declared SLA. Service-ineligible candidates remain visible but are excluded.", "",
                          "| Candidate | Status | Service eligible | Pareto candidate | Facility kWh | Cost CNY | Grid kg CO₂ | Individual minima |",
                          "|---|---|:---:|:---:|---:|---:|---:|---|"])
            for row in objective_rows:
                minima_labels = [label for key, label, field in (
                    ("facility_kwh", "facility electricity", "minimum_facility_kwh"),
                    ("cost_cny", "cost", "minimum_cost_cny"),
                    ("emissions_kg", "emissions", "minimum_emissions_kg"),
                ) if row.get(field) is True]
                lines.append("| " + " | ".join((
                    _md(row.get("controller_label") or row.get("controller")),
                    _md(row.get("objective_candidate_status") or "unavailable"),
                    _display(row.get("objective_service_eligible")),
                    _display(row.get("pareto_frontier_candidate")),
                    _display(row.get("facility_kwh")), _display(row.get("cost_cny")),
                    _display(row.get("emissions_kg")), ", ".join(minima_labels) or "—",
                )) + " |")
            lines.append("")
        elif objective_rows:
            lines.extend(["### Three-objective candidate frontier", "", "Unavailable: this simulator response predates canonical Pareto analysis.", ""])
        if baseline_row:
            baseline_label = baseline_row.get("controller_label") or "Unscheduled baseline"
            selected_name = next((row.get("selected_policy") for row in policy_rows if row.get("selected_policy")), None)
            selected = next((row for row in policy_rows if row.get("controller") == selected_name), None)
            if selected is None:
                selected = next((row for row in policy_rows if row.get("controller") == "forecast"), None)
            if selected and selected.get("canonical_comparison_status") == "available":
                lines.append(f"**Selected policy ({selected.get('controller_label')}) vs {baseline_label}:** "
                             f"facility electricity {_reduction_phrase(selected, 'electricity')} "
                             f"({_display(baseline_row.get('facility_kwh'))} → {_display(selected.get('facility_kwh'))} kWh); "
                             f"grid imports {_reduction_phrase(selected, 'grid_import')} "
                             f"({_display(baseline_row.get('grid_kwh'))} → {_display(selected.get('grid_kwh'))} kWh); "
                             f"cost {_reduction_phrase(selected, 'cost')} "
                             f"({_display(baseline_row.get('cost_cny'))} → {_display(selected.get('cost_cny'))} CNY); "
                             f"operational emissions {_reduction_phrase(selected, 'emissions')} "
                             f"({_display(baseline_row.get('emissions_kg'))} → {_display(selected.get('emissions_kg'))} kg CO₂).")
                if selected.get("canonical_service_comparable") is False:
                    lines.append(f" Service equivalence failed: {_md(selected.get('canonical_service_note') or 'service outcomes differ')}. Reported percentage values are retained in the CSV but withheld from savings claims.")
            elif not any(row.get("canonical_comparison_status") == "available" for row in policy_rows):
                lines.append("Canonical per-controller savings are unavailable because the response omitted or incompletely populated `comparisons`.")
            lines.extend(["", f"Unscheduled baseline: **{baseline_label}** (all nodes active; immediate FIFO/ASAP work; no energy scheduling).", ""])
        else:
            if any(row.get("status") != "complete" for row in group):
                lines.extend(["**No simulator result is available for this scenario.** The baseline and controller metrics could not be produced.", ""])
            else:
                lines.extend(["**Canonical unscheduled comparison unavailable.** This older response does not include `unscheduled_baseline` and `comparisons`; the existing `always_on` controller is an LP-scheduled diagnostic, not the naive baseline.", ""])

        lines.extend([
            "### Energy and cost comparison",
            "",
            "Percentages below use the simulator's canonical unscheduled-baseline comparisons. A blank percentage means the API omitted it, the denominator was zero/unavailable, or service equivalence failed.",
            "",
            "| Result | Status | Facility electricity kWh | Facility reduction % | Grid import kWh | Grid reduction % | Cost CNY | Cost reduction % | Emissions kg CO₂ | Emissions reduction % | Service comparable |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
        ])
        ordered = ([baseline_row] if baseline_row else []) + policy_rows
        for row in ordered:
            if row.get("status") != "complete":
                lines.append(f"| {_md(row.get('controller_label') or row.get('controller'))} | FAILED | — | — | — | — | — | — | — | — | — |")
                continue
            reduction = lambda field: _display(row.get(f"{field}_savings_pct"))
            service = ("baseline" if row.get("record_kind") == "unscheduled_baseline"
                       else _display(row.get("canonical_service_comparable")))
            lines.append("| " + " | ".join((
                _md(row.get("controller_label") or row.get("controller")), "complete",
                _display(row.get("facility_kwh")), reduction("electricity"),
                _display(row.get("grid_kwh")), reduction("grid_import"),
                _display(row.get("cost_cny")), reduction("cost"),
                _display(row.get("emissions_kg")), reduction("emissions"), service,
            )) + " |")
        lines.extend(["", "### Scheduled-controller diagnostic", "",
                      "This retains the earlier comparison among LP-scheduled controllers; `always_on` here is not the no-scheduling baseline.",
                      "",
                      "| Scheduled controller | Cost CNY | Cost delta vs scheduled always-on | Request terminal outcomes match? |", "|---|---:|---:|:---:|"])
        for row in policy_rows:
            if row.get("status") != "complete":
                lines.append(f"| {_md(row.get('controller_label') or row.get('controller'))} | FAILED | — | — |")
                continue
            if row.get("cost_savings_pct_vs_always_on") is not None:
                legacy_change = f"{row['cost_change_cny_vs_always_on']:+.3f} CNY ({row['cost_savings_pct_vs_always_on']:+.2f}%)"
            elif row.get("cost_change_cny_vs_always_on") is not None:
                legacy_change = f"{row['cost_change_cny_vs_always_on']:+.3f} CNY (percentage unavailable)"
            else:
                legacy_change = "—"
            matched = ("always-on reference" if row.get("controller") == "always_on"
                       else "yes" if row.get("cost_savings_pct_vs_always_on") is not None
                       else "no / unavailable")
            lines.append(f"| {_md(row.get('controller_label') or row.get('controller'))} | {_display(row.get('cost_cny'))} | {legacy_change} | {matched} |")
        lines.extend(["", "### Service performance", "",
                      "| Result | Completed | Queued at horizon | Running at horizon | Rejected | Mean / P95 wait min | Mean completion latency min | Flex admission | Flex delivered / unmet GPU-h | Flex deadlines met | Service note |",
                      "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|"])
        for row in ordered:
            if row.get("status") != "complete":
                lines.append(f"| {_md(row.get('controller_label') or row.get('controller'))} | FAILED | — | — | — | — | — | — | — | — | {_md(row.get('error'))} |")
                continue
            waits = f"{_display(row.get('mean_wait_minutes'))} / {_display(row.get('p95_wait_minutes'))}"
            flex = f"{_display(row.get('flexible_gpu_hours_delivered'))} / {_display(row.get('flexible_gpu_hours_unmet'))}"
            admission = _display(row.get("flexible_admission_status"))
            if row.get("flexible_admission_reason"):
                admission += f": {_md(row['flexible_admission_reason'])}"
            service_note = row.get("canonical_service_note") or row.get("cost_comparison_note") or "—"
            lines.append("| " + " | ".join((
                _md(row.get("controller_label") or row.get("controller")),
                _display(row.get("requests_completed")), _display(row.get("requests_queued_at_horizon")),
                _display(row.get("requests_running_at_horizon")), _display(row.get("requests_rejected")),
                waits, _display(row.get("mean_completion_latency_minutes")), admission, flex,
                f"{_display(row.get('flexible_jobs_deadline_met'))} / {_display(row.get('flexible_jobs_admitted'))}",
                _md(service_note),
            )) + " |")
        lines.extend(["", "The scheduled `always_on` row uses the existing flexible-job LP and remains separate from the no-scheduling baseline.",
                      "The legacy `cost_change_cny_vs_always_on` and `cost_savings_pct_vs_always_on` columns in `summary.csv` are diagnostic comparisons among scheduled controllers only.",
                      "Queue/wait, flexible-work, fleet/forecast shortfalls, node-state minutes and raw simulator-reported canonical percentages are available in `summary.csv`.", ""])
        for row in policy_rows:
            if row.get("status") == "complete" and row.get("cost_comparison_note"):
                lines.append(f"- {row['controller']} vs scheduled always-on diagnostic: {row['cost_comparison_note']}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, report_path


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _reduction_phrase(row: dict[str, Any], metric: str) -> str:
    value = row.get(f"{metric}_savings_pct")
    if value is not None:
        if value > 0:
            return f"{value:.2f}% reduction"
        if value < 0:
            return f"{abs(value):.2f}% increase"
        return "0.00% change"
    reported = row.get(f"{metric}_pct_reported")
    if row.get("canonical_service_comparable") is False:
        if reported is not None:
            return f"not comparable (raw modeled change {reported:+.2f}%; not a savings claim)"
        return "not comparable; percentage unavailable"
    if row.get("canonical_service_comparable") is None and reported is not None:
        return f"service equivalence unavailable (raw {reported:+.2f}%; not a savings claim)"
    reason = row.get(f"{metric}_savings_reason")
    if reason:
        return f"percentage unavailable ({_md(reason)})"
    return "percentage unavailable"


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[2026], help="One or more reproducible 32-bit seeds (default: 2026).")
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS), help="Scenarios to run (default: all).")
    parser.add_argument("--output-dir", type=Path, help="Directory for summary.csv and report.md.")
    parser.add_argument("--forecast-alpha", type=float, default=0.3)
    parser.add_argument("--margin-fraction", type=float, default=0.15)
    parser.add_argument("--min-active-fraction", type=float, default=0.25)
    return parser


def main(argv: list[str] | None = None, *, runner: Callable[[dict[str, Any]], dict[str, Any]] = run_dynamic_comparison) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if any(seed < 0 or seed > 2**31 - 1 for seed in args.seeds):
        parser.error("Seeds must be nonnegative 32-bit integers.")
    if not 0.05 <= args.forecast_alpha <= 0.8:
        parser.error("--forecast-alpha must be between 0.05 and 0.8.")
    if not 0 <= args.margin_fraction <= 1 or not 0 <= args.min_active_fraction <= 1:
        parser.error("--margin-fraction and --min-active-fraction must be between 0 and 1.")
    output_dir = args.output_dir or PROJECT_ROOT / "results" / "operational-experiments" / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    rows = run_batch(args.seeds, args.scenarios, runner=runner,
                     forecast_alpha=args.forecast_alpha, margin_fraction=args.margin_fraction,
                     min_active_fraction=args.min_active_fraction)
    csv_path, report_path = write_outputs(rows, output_dir, seeds=args.seeds,
                                          scenario_names=args.scenarios)
    failures = sum(row.get("status") != "complete" for row in rows)
    print(f"Wrote {csv_path}")
    print(f"Wrote {report_path}")
    print(f"Controller rows: {len(rows)}; failed rows: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
