from backend.dynamic_simulation import (
    Node,
    _arrival_rate_forecasts,
    _compare_to_unscheduled_baseline,
    _forecast_margin,
    _offered_gpu_trace,
    _projected_active_capacity,
    _scale_up,
    _choose_waiting_request,
    _advance_transitions,
    _ensure_warm_reserve,
    _warm_target,
    generate_requests,
    run_dynamic_comparison,
)


def test_synthetic_trace_is_seeded_and_forecast_is_causal():
    first = generate_requests(17, burst=False)
    assert first == generate_requests(17, burst=False)
    changed_future = [dict(request) for request in first]
    changed_future.extend({"id": f"future-{i}", "class": "interactive", "arrival": 500,
                           "gpus": 2, "duration": 5} for i in range(100))
    forecast = _arrival_rate_forecasts(first, alpha=0.3, generator_prior=False)
    forecast_after_change = _arrival_rate_forecasts(changed_future, alpha=0.3, generator_prior=False)
    assert forecast[:100] == forecast_after_change[:100]
    assert forecast[101] != forecast_after_change[101]


def test_adopted_warm_target_uses_active_spare_and_rounds_whole_nodes():
    reference = _warm_target([78 + 10], active_nodes=8, nodes=12, gpus_per_node=8)
    assert reference["target_warm_nodes"] == 3
    assert reference["target_warm_fleet_shortfall_nodes"] == 0
    assert _warm_target([64], active_nodes=8, nodes=12, gpus_per_node=8)["target_warm_nodes"] == 0
    assert _warm_target([65], active_nodes=8, nodes=12, gpus_per_node=8)["target_warm_nodes"] == 1


def test_warm_target_reports_uncapped_fleet_shortfall():
    reserve = _warm_target([101], active_nodes=8, nodes=12, gpus_per_node=8)
    assert reserve["target_warm_nodes"] == 5
    assert reserve["target_warm_realizable_nodes"] == 4
    assert reserve["target_warm_fleet_shortfall_nodes"] == 1
    assert reserve["peak_fleet_shortfall_gpus"] == 5


def test_warm_and_cold_readiness_are_distinct_and_pipeline_counts_once():
    nodes = [Node("active"), Node("warm"), Node("warming", remaining=5),
             Node("booting", remaining=20), Node("off")]
    assert _projected_active_capacity(nodes, 4, 8) == 8
    assert _projected_active_capacity(nodes, 5, 8) == 24
    assert _projected_active_capacity(nodes, 24, 8) == 24
    assert _projected_active_capacity(nodes, 25, 8) == 32
    _ensure_warm_reserve(nodes, target_warm=3)
    assert [node.state for node in nodes].count("booting") == 1
    assert [node.state for node in nodes].count("warm") == 1
    assert [node.state for node in nodes].count("off") == 1


def test_forecast_margin_uses_matured_error_then_labeled_assumption_fallback():
    margin, source = _forecast_margin([], 80, 0.15, 4)
    assert margin == 12
    assert source == "manual_assumption_fallback"
    margin, source = _forecast_margin([0, 2, 10] * 10, 80, 0.15, 4)
    assert margin == 10
    assert source == "matured_synthetic_window_q95"


def test_warm_node_activation_respects_delay_state_and_fleet_conservation():
    nodes = [Node("active"), Node("warm"), Node("off")]
    _scale_up(nodes, target_active=2, gpn=8)
    assert [node.state for node in nodes] == ["active", "warming", "off"]
    assert nodes[1].remaining == 5
    for _ in range(4):
        _advance_transitions(nodes)
    assert nodes[1].state == "warming"
    _advance_transitions(nodes)
    assert nodes[1].state == "active"
    assert sum(node.state in {"active", "warm", "warming", "booting", "off"} for node in nodes) == 3

    cold = [Node("off")]
    _ensure_warm_reserve(cold, target_warm=1)
    for _ in range(19):
        _advance_transitions(cold)
    assert cold[0].state == "booting"
    _advance_transitions(cold)
    assert cold[0].state == "warm"
    _scale_up(cold, target_active=1, gpn=8)
    assert cold[0].state == "warming" and cold[0].remaining == 5


def test_comparison_uses_same_offered_work_and_balanced_energy():
    result = run_dynamic_comparison({"seed": 2026, "nodes": 8, "gpus_per_node": 8, "bursts": False})
    assert result["requests_generated"] > 0
    metrics = [p["metrics"] for p in result["policies"].values()]
    assert len({m["offered_gpu_minutes"] for m in metrics}) == 1
    for policy in result["policies"].values():
        m = policy["metrics"]
        assert abs(m["facility_kwh"] - m["grid_kwh"] - m["renewable_used_kwh"]) < 0.01
        assert abs(m["emissions_kg"] - m["grid_kwh"] * 0.55) < 0.01
        assert 0.38648119 * m["grid_kwh"] <= m["cost_cny"] <= 0.83855171 * m["grid_kwh"]
        assert m["served_gpu_minutes"] <= m["offered_gpu_minutes"]
        assert m["requests_completed"] + m["requests_queued_at_horizon"] + m["requests_running_at_horizon"] + m["requests_rejected"] == result["requests_generated"]
        assert all(sum(row[k] for k in ("active_nodes", "warm_nodes", "booting_nodes", "off_nodes")) == result["nodes"] for row in policy["state_trace"])
        assert abs(policy["metrics"]["energy_accounted_gpu_minutes"] - policy["metrics"]["served_gpu_minutes"] - policy["metrics"]["flexible_gpu_hours_delivered"] * 60) < 0.1


def test_invalid_hardware_rejected():
    try:
        run_dynamic_comparison({"nodes": 1})
    except ValueError as exc:
        assert "2–64 nodes" in str(exc)
    else:
        raise AssertionError("invalid inventory should be rejected")
    try:
        run_dynamic_comparison({"nodes": 2.5})
    except ValueError as exc:
        assert "whole number" in str(exc)
    else:
        raise AssertionError("fractional node count should be rejected")


def test_dynamic_simulation_api_returns_policy_comparison():
    from server import app

    response = app.test_client().post("/api/dynamic-simulation", json={"seed": 2, "nodes": 4, "gpus_per_node": 8, "bursts": False})
    assert response.status_code == 200
    body = response.get_json()
    assert set(body["policies"]) == {"always_on", "reactive", "forecast"}
    assert body["selected_policy"] == "forecast"
    assert body["unscheduled_baseline"]["label"] == "Always-on FIFO / ASAP (no energy scheduling)"
    assert set(body["comparisons"]) == set(body["policies"])
    assert set(body["comparisons"]["forecast"]["savings"]) == {
        "electricity_pct", "cost_pct", "emissions_pct", "grid_import_pct"}
    assert "requests_running_at_horizon" in body["unscheduled_baseline"]["metrics"]
    assert body["flexible_schedule"]["admission_status"] == "infeasible"
    replay = body["policies"]["forecast"]["replay"]
    assert replay["node_ids"] == ["node-01", "node-02", "node-03", "node-04"]
    assert len(replay["frames"]) == 1440
    assert replay["frames"][0]["minute"] == 0
    assert {"states", "used_gpus", "power_kw", "facility_kw", "grid_kwh", "renewable_used_kwh",
            "cumulative_cost_cny", "cumulative_grid_kwh", "cumulative_emissions_kg"} <= replay["frames"][0].keys()


def test_batch_aging_prevents_new_work_from_backfilling_an_aged_head():
    from collections import deque

    statuses = {
        "batch-old": {"class": "batch", "arrival": 0, "gpus": 8},
        "interactive-new": {"class": "interactive", "arrival": 16, "gpus": 1},
    }
    waiting = deque(statuses)
    assert _choose_waiting_request(waiting, statuses, minute=16, free_gpus=4) is None
    assert _choose_waiting_request(waiting, statuses, minute=16, free_gpus=8) == "batch-old"


def test_flexible_commitment_is_protected_and_completes_by_deadline_under_all_controllers():
    flexible = [{"id": "committed", "name": "Committed training", "arrival": 0,
                 "deadline": 2, "gpu_hours": 20, "max_gpus": 20, "tier": "pro"}]
    burst = [{"id": f"burst-{i}", "class": "interactive", "arrival": 0,
              "gpus": 8, "duration": 30, "latency": 2} for i in range(20)]
    result = run_dynamic_comparison({"nodes": 12, "gpus_per_node": 8, "seed": 11,
                                     "bursts": False, "flexible_jobs": flexible,
                                     "request_trace": burst})
    assert result["flexible_schedule"]["admission_status"] == "admitted"
    for policy in result["policies"].values():
        metrics = policy["metrics"]
        assert metrics["flexible_jobs_admitted"] == 1
        assert metrics["flexible_jobs_deadline_met"] == 1
        assert metrics["flexible_gpu_hours_scheduled"] == 20
        assert metrics["flexible_gpu_hours_delivered"] == 20
        assert metrics["flexible_gpu_hours_unmet"] == 0
        assert metrics["flexible_commitment_missed_gpu_minutes"] == 0
        assert metrics["energy_accounted_gpu_minutes"] == metrics["served_gpu_minutes"] + 20 * 60
        assert metrics["requests_completed"] == 20
        assert metrics["p95_wait_minutes"] > 0


def test_flexible_admission_reports_capacity_and_deadline_infeasibility():
    impossible = [{"id": "too-large", "name": "Infeasible batch", "arrival": 0,
                   "deadline": 1, "gpu_hours": 100, "max_gpus": 100, "tier": "pro"}]
    result = run_dynamic_comparison({"nodes": 12, "gpus_per_node": 8, "seed": 11,
                                     "bursts": False, "flexible_jobs": impossible,
                                     "request_trace": []})
    assert result["flexible_schedule"]["admission_status"] == "infeasible"
    assert result["flexible_schedule"]["admission_reason"] == "Infeasible"
    for policy in result["policies"].values():
        assert policy["metrics"]["flexible_jobs_admitted"] == 0
        assert policy["metrics"]["flexible_gpu_hours_scheduled"] == 0
        assert policy["metrics"]["flexible_gpu_hours_unmet"] == 100
        assert policy["flexible_jobs"][0]["status"] == "not_admitted"


def test_default_flexible_lp_work_is_shared_delivered_and_deadline_safe():
    result = run_dynamic_comparison({"nodes": 32, "gpus_per_node": 8, "seed": 2026, "bursts": False})
    assert result["flexible_schedule"]["admission_status"] == "admitted"
    scheduled = result["flexible_schedule"]["scheduled_gpu_hours"]
    assert scheduled == 3060
    for policy in result["policies"].values():
        metrics = policy["metrics"]
        assert metrics["flexible_gpu_hours_delivered"] == scheduled
        assert metrics["flexible_gpu_hours_unmet"] == 0
        assert metrics["flexible_jobs_deadline_met"] == len(result["flexible_jobs"])
        assert all(abs(row["forecast_window_peak_predicted_gpus"]
                       - row["forecast_window_peak_realtime_gpus"]
                       - row["forecast_window_peak_flexible_gpus"]) < 0.02
                   for row in policy["state_trace"])


def test_unscheduled_baseline_uses_same_trace_and_reports_actual_savings_and_service():
    result = run_dynamic_comparison({"nodes": 12, "gpus_per_node": 8, "seed": 2026,
                                     "bursts": False, "request_trace": []})
    baseline = result["unscheduled_baseline"]
    assert baseline["label"] == "Always-on FIFO / ASAP (no energy scheduling)"
    assert baseline["metrics"]["offered_gpu_minutes"] == 0
    assert set(result["comparisons"]) == set(result["policies"])
    for key, comparison in result["comparisons"].items():
        b = comparison["baseline"]["metrics"]
        optimized = comparison["optimized"]["metrics"]
        assert comparison["baseline"]["key"] == "unscheduled"
        assert comparison["optimized"]["key"] == key
        assert b["facility_kwh"] == baseline["metrics"]["facility_kwh"]
        if b["facility_kwh"]:
            expected = (b["facility_kwh"] - optimized["facility_kwh"]) / b["facility_kwh"] * 100
            assert abs(comparison["savings"]["electricity_pct"] - expected) < 0.001
        assert comparison["service_comparable"]


def test_savings_comparison_flags_changed_terminal_service_outcomes():
    trace = [{"id": f"last-minute-{i}", "class": "interactive", "arrival": 1439,
              "gpus": 8, "duration": 2, "latency": 1} for i in range(5)]
    result = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8, "seed": 2026,
                                     "bursts": False, "request_trace": trace, "flexible_jobs": []})
    comparison = result["comparisons"]["forecast"]
    assert not comparison["service_comparable"]
    assert "Service outcomes differ" in comparison["service_note"]
    assert comparison["baseline"]["metrics"]["requests_running_at_horizon"] == 5
    assert comparison["optimized"]["metrics"]["requests_queued_at_horizon"] > 0


def test_unscheduled_baseline_runs_same_lp_accepted_flexible_jobs_asap():
    jobs = [{"id": "same-work", "name": "Same work", "arrival": 0,
             "deadline": 2, "gpu_hours": 20, "max_gpus": 20, "tier": "pro"}]
    result = run_dynamic_comparison({"nodes": 12, "gpus_per_node": 8, "seed": 2026,
                                     "bursts": False, "request_trace": [], "flexible_jobs": jobs})
    baseline = result["unscheduled_baseline"]
    assert baseline["accepted_flexible_job_ids"] == ["same-work"]
    assert baseline["metrics"]["flexible_gpu_hours_scheduled"] == 20
    assert baseline["metrics"]["flexible_gpu_hours_delivered"] == 20
    assert baseline["flexible_jobs"][0]["deadline_met"]
    for item in result["comparisons"].values():
        assert item["service_comparable"]


def test_zero_baseline_denominator_returns_null_with_reason():
    metrics = {"facility_kwh": 0, "grid_kwh": 0, "cost_cny": 0, "emissions_kg": 0}
    result = _compare_to_unscheduled_baseline(
        {"label": "baseline", "metrics": metrics, "request_status_by_id": {}, "flexible_jobs": []},
        {"label": "controller", "metrics": metrics, "replay": {"requests": []}, "flexible_jobs": []},
        "forecast")
    assert all(value is None for value in result["savings"].values())
    assert all(value and "zero" in value.lower() for value in result["savings_reason"].values())


def test_replay_frames_match_energy_accounting_and_request_lifecycle():
    trace = [
        {"id": "early", "class": "interactive", "arrival": 2, "gpus": 2, "duration": 3},
        {"id": "late", "class": "batch", "arrival": 20, "gpus": 4, "duration": 10},
    ]
    result = run_dynamic_comparison({"nodes": 4, "gpus_per_node": 8, "seed": 4,
                                     "bursts": False, "request_trace": trace})
    for policy in result["policies"].values():
        replay = policy["replay"]
        metrics = policy["metrics"]
        assert len(replay["node_ids"]) == 4
        assert len(replay["frames"]) == 1440
        assert len(replay["requests"]) == 2
        assert [row["id"] for row in replay["requests"]] == ["early", "late"]
        assert replay["requests"][0]["arrival_minute"] == 2
        assert replay["requests"][0]["completed_at_minute"] == 5
        assert replay["requests"][1]["started_at_minute"] == 20
        assert replay["requests"][1]["completed_at_minute"] == 30
        assert all(len(frame["states"]) == len(frame["power_kw"]) == len(frame["used_gpus"]) == 4
                   for frame in replay["frames"])
        for frame in replay["frames"]:
            # Node-level power is IT draw, excluding shared 18kW site load and PUE.
            assert abs(sum(frame["power_kw"]) + 18 - frame["facility_kw"] / 1.25) < 0.001
            assert sum(frame["used_gpus"]) <= 32
        assert abs(sum(f["facility_kw"] / 60 for f in replay["frames"]) - metrics["facility_kwh"]) < 0.01
        assert abs(sum(f["grid_kwh"] for f in replay["frames"]) - metrics["grid_kwh"]) < 0.01
        assert abs(replay["frames"][-1]["cumulative_cost_cny"] - metrics["cost_cny"]) < 0.001
