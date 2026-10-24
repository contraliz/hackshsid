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


def test_cli_rejects_unsupported_renewable_controls():
    # The CLI surface deliberately has no renewable override: the API exposes no such input.
    from tools.operational_experiments import make_parser

    options = {action.dest for action in make_parser()._actions}
    assert "renewables" not in options


def test_cli_rejects_out_of_range_seed(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--seeds", str(2**31), "--scenarios", "normal_day", "--output-dir", str(tmp_path)])
    assert error.value.code == 2
