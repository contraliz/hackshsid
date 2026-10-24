import csv
import json

import pytest

from tools.operational_experiments import (
    CONTROLLERS,
    SCENARIOS,
    build_scenario,
    cost_comparison,
    main,
    run_batch,
    same_service_outcome,
    write_outputs,
)


def _policy(status="completed", cost=10.0):
    return {
        "metrics": {
            "cost_cny": cost,
            "requests_completed": 1 if status == "completed" else 0,
            "flexible_jobs_deadline_met": 1,
            "flexible_gpu_hours_delivered": 2.0,
        },
        "flexible_jobs": [{"id": "job-a", "admitted": True, "deadline_met": True,
                            "delivered_gpu_hours": 2.0, "unmet_gpu_hours": 0.0}],
        "replay": {"requests": [{"id": "request-a", "status": status}],
                    "frames": [{"states": ["active", "off"]},
                               {"states": ["warm", "off"]}]},
    }


def _result(*, status="completed", cost=10.0):
    return {
        "nodes": 2, "gpus_per_node": 4, "fleet_gpus": 8,
        "requests_generated": 1,
        "flexible_schedule": {"admission_status": "admitted"},
        "assumptions": {"data_status": "synthetic_illustrative_not_measurements",
                        "tariff": "proxy", "tariff_reference_url": "https://example.invalid/tariff",
                        "grid_emissions": "annual average proxy",
                        "grid_emissions_reference_url": "https://example.invalid/grid"},
        "policies": {name: _policy(status, cost + (0 if name == "always_on" else -1))
                     for name in CONTROLLERS},
    }


def _canonical_result(*, service_comparable=True, zero_denominator=False):
    result = _result()
    baseline_metrics = {
        "facility_kwh": 100.0, "grid_kwh": 70.0, "renewable_used_kwh": 30.0,
        "renewable_curtailed_kwh": 0.0, "cost_cny": 20.0, "emissions_kg": 38.5,
        "requests_completed": 1, "requests_rejected": 0, "requests_queued_at_horizon": 0,
        "requests_running_at_horizon": 0, "mean_wait_minutes": 1.0, "p95_wait_minutes": 2.0,
        "mean_completion_latency_minutes": 3.0, "latency_allowance_met": 1,
        "latency_allowance_total": 1, "flexible_jobs_admitted": 1,
        "flexible_jobs_deadline_met": 1, "flexible_gpu_hours_scheduled": 2.0,
        "flexible_gpu_hours_delivered": 2.0, "flexible_gpu_hours_unmet": 0.0,
        "flexible_deadline_misses": 0, "flexible_commitment_missed_gpu_minutes": 0.0,
    }
    if zero_denominator:
        for key in ("facility_kwh", "grid_kwh", "cost_cny", "emissions_kg"):
            baseline_metrics[key] = 0.0
    baseline = {
        "label": "Always-on FIFO / ASAP (no energy scheduling)",
        "metrics": baseline_metrics, "flexible_admission_status": "admitted",
        "flexible_admission_reason": None,
        "flexible_jobs": [{"id": "job-a", "admitted": True, "deadline_met": True,
                            "delivered_gpu_hours": 2.0, "unmet_gpu_hours": 0.0}],
    }
    comparisons = {}
    for controller, policy in result["policies"].items():
        policy["metrics"].update({
            "facility_kwh": 85.0, "grid_kwh": 56.0, "renewable_used_kwh": 29.0,
            "renewable_curtailed_kwh": 0.0, "cost_cny": 17.5, "emissions_kg": 30.8,
            "requests_queued_at_horizon": 0, "requests_running_at_horizon": 0,
            "requests_rejected": 0, "mean_wait_minutes": 2.0,
            "p95_wait_minutes": 4.0, "mean_completion_latency_minutes": 5.0,
            "latency_allowance_met": 1, "latency_allowance_total": 1,
            "flexible_gpu_hours_unmet": 0.0, "flexible_jobs_admitted": 1,
            "flexible_jobs_deadline_met": 1, "flexible_gpu_hours_scheduled": 2.0,
            "flexible_deadline_misses": 0, "flexible_commitment_missed_gpu_minutes": 0.0,
        })
        savings = {
            "electricity_pct": None if zero_denominator else 14.99,
            "grid_import_pct": None if zero_denominator else 20.0,
            "cost_pct": None if zero_denominator else 12.49,
            "emissions_pct": None if zero_denominator else 20.0,
        }
        comparisons[controller] = {
            "baseline": {"key": "unscheduled", "label": baseline["label"], "metrics": baseline_metrics},
            "optimized": {"key": controller, "label": policy.get("label", controller), "metrics": policy["metrics"]},
            "savings": savings,
            "savings_reason": {key: "Baseline denominator is zero." for key, value in savings.items() if value is None},
            "service_comparable": service_comparable,
            "service_note": "Same completed request and flexible-job outcomes; latency differs." if service_comparable else "One or more requests missed or remained unfinished.",
        }
    if zero_denominator:
        for item in comparisons.values():
            item["optimized"]["metrics"].update({key: 0.0 for key in ("facility_kwh", "grid_kwh", "cost_cny", "emissions_kg")})
    result["unscheduled_baseline"] = baseline
    result["comparisons"] = comparisons
    result["selected_policy"] = "forecast"
    return result


def test_scenarios_are_seeded_and_constrained_trace_is_supported():
    first = build_scenario("demand_burst", 2026)
    again = build_scenario("demand_burst", 2026)
    assert first["payload"] == again["payload"]
    assert first["config"]["burst_total_gpus"] == 320
    assert len(first["payload"]["request_trace"]) == first["config"]["request_count"]
    assert first["config"]["request_count"] > 80

    constrained = build_scenario("constrained_fleet", 2026)
    assert constrained["payload"]["nodes"] * constrained["payload"]["gpus_per_node"] == 8
    assert max(item["gpus"] for item in constrained["payload"]["request_trace"]) == 8
    assert set(SCENARIOS) == {"normal_day", "demand_burst", "constrained_fleet"}


def test_run_batch_calls_shared_comparison_once_and_summarizes_node_states():
    calls = []

    def fake_runner(payload):
        calls.append(payload)
        return _result()

    rows = run_batch([31], ["normal_day"], runner=fake_runner)
    assert len(calls) == 1
    assert len(rows) == 3
    assert {row["controller"] for row in rows} == set(CONTROLLERS)
    assert all(row["status"] == "complete" for row in rows)
    assert all(row["flexible_admission_status"] == "admitted" for row in rows)
    assert rows[0]["state_active_node_minutes"] == 1
    assert rows[0]["state_warm_node_minutes"] == 1
    assert rows[0]["state_off_node_minutes"] == 2
    assert rows[0]["state_transition_count"] == 1
    assert rows[1]["cost_savings_pct_vs_always_on"] == 10.0
    assert json.loads(rows[0]["scenario_config_json"])["nodes"] == 32


def test_cost_percent_handles_zero_and_different_service_results():
    assert cost_comparison(3, 0, comparable=True) == (-3, None, "Absolute difference shown; percentage unavailable because always-on cost is zero.")
    assert cost_comparison(3, 10, comparable=False)[0] is None
    assert not same_service_outcome(_policy("queued"), _policy("completed"))


def test_different_service_statuses_suppress_cost_savings():
    def result_with_difference(_payload):
        result = _result()
        result["policies"]["reactive"] = _policy("queued", cost=1.0)
        return result

    rows = run_batch([5], ["normal_day"], runner=result_with_difference)
    reactive = next(row for row in rows if row["controller"] == "reactive")
    assert reactive["cost_change_cny_vs_always_on"] is None
    assert reactive["cost_savings_pct_vs_always_on"] is None
    assert "outcomes differ" in reactive["cost_comparison_note"]


def test_canonical_unscheduled_savings_and_service_report(tmp_path):
    rows = run_batch([2026], ["normal_day"], runner=lambda _payload: _canonical_result())
    baseline = next(row for row in rows if row["record_kind"] == "unscheduled_baseline")
    forecast = next(row for row in rows if row["controller"] == "forecast")
    assert baseline["controller_label"] == "Always-on FIFO / ASAP (no energy scheduling)"
    assert baseline["facility_kwh"] == 100.0
    assert forecast["unscheduled_baseline_grid_kwh"] == 70.0
    assert forecast["electricity_savings_pct"] == 14.99
    assert forecast["grid_import_savings_pct"] == 20.0
    assert forecast["cost_savings_pct"] == 12.49
    assert forecast["emissions_savings_pct"] == 20.0
    # The canonical percentages are consumed, not recalculated from rounded fixture values.
    csv_path, report_path = write_outputs(rows, tmp_path, seeds=[2026], scenario_names=["normal_day"])
    report = report_path.read_text(encoding="utf-8")
    assert "14.99% reduction" in report
    assert "12.49% reduction" in report
    assert "100 → 85 kWh" in report
    assert "Service performance" in report
    assert "it is not the unscheduled baseline" in report
    with csv_path.open(encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == 4


def test_noncomparable_service_keeps_raw_backend_percent_but_withholds_savings(tmp_path):
    rows = run_batch([4], ["normal_day"], runner=lambda _payload: _canonical_result(service_comparable=False))
    forecast = next(row for row in rows if row["controller"] == "forecast")
    assert forecast["canonical_service_comparable"] is False
    assert forecast["electricity_pct_reported"] == 14.99
    assert forecast["electricity_savings_pct"] is None
    _, report_path = write_outputs(rows, tmp_path, seeds=[4], scenario_names=["normal_day"])
    report = report_path.read_text(encoding="utf-8")
    assert "not comparable (raw modeled change +14.99%; not a savings claim)" in report
    assert "Service equivalence failed" in report


def test_zero_denominator_percentages_remain_unavailable_and_legacy_response_warns(tmp_path):
    rows = run_batch([7], ["normal_day"], runner=lambda _payload: _canonical_result(zero_denominator=True))
    forecast = next(row for row in rows if row["controller"] == "forecast")
    assert forecast["electricity_savings_pct"] is None
    assert forecast["electricity_pct_reported"] is None
    _, report_path = write_outputs(rows, tmp_path / "zero", seeds=[7], scenario_names=["normal_day"])
    assert "percentage unavailable (Baseline denominator is zero.)" in report_path.read_text(encoding="utf-8")

    legacy_rows = run_batch([7], ["normal_day"], runner=lambda _payload: _result())
    assert len(legacy_rows) == 3
    _, legacy_report = write_outputs(legacy_rows, tmp_path / "legacy", seeds=[7], scenario_names=["normal_day"])
    report = legacy_report.read_text(encoding="utf-8")
    assert "Canonical unscheduled comparison unavailable" in report
    assert "LP-scheduled diagnostic, not the naive baseline" in report


def test_missing_metrics_stay_unavailable_and_outputs_have_expected_schema(tmp_path):
    def incomplete_runner(_payload):
        result = _result()
        for policy in result["policies"].values():
            policy["metrics"].pop("p95_wait_minutes", None)
        return result

    rows = run_batch([2], ["normal_day"], runner=incomplete_runner)
    assert all(row["p95_wait_minutes"] is None for row in rows)
    csv_path, report_path = write_outputs(rows, tmp_path, seeds=[2], scenario_names=["normal_day"])
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        records = list(reader)
        assert "p95_wait_minutes" in reader.fieldnames
        assert len(records) == 3
        assert all(record["p95_wait_minutes"] == "" for record in records)
    report = report_path.read_text(encoding="utf-8")
    assert "synthetic and illustrative" in report
    assert "agent-purchase" not in report or "proxy" in report


def test_failures_are_exported_and_cli_returns_nonzero(tmp_path, capsys):
    def fail(_payload):
        raise RuntimeError("simulator unavailable")

    exit_code = main(["--seeds", "8", "--scenarios", "normal_day", "--output-dir", str(tmp_path)], runner=fail)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "failed rows: 3" in out
    with (tmp_path / "summary.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["status"] for row in rows} == {"failed"}
    assert all("RuntimeError: simulator unavailable" in row["error"] for row in rows)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "No simulator result is available for this scenario" in report


def test_cli_rejects_unsupported_renewable_controls():
    # The CLI surface deliberately has no renewable override: the API exposes no such input.
    from tools.operational_experiments import make_parser

    options = {action.dest for action in make_parser()._actions}
    assert "renewables" not in options


def test_cli_rejects_out_of_range_seed(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--seeds", str(2**31), "--scenarios", "normal_day", "--output-dir", str(tmp_path)])
    assert error.value.code == 2
