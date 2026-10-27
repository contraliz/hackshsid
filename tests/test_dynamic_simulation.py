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
    _warm_stock_pipeline_nodes,
    _workload_gpu_minutes_per_request,
    _expected_future_arrival_concurrency,
    _plan_active_readiness,
    _rounded_duration_distribution,
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


def test_duration_draws_follow_min_typical_max_and_factors_match_rounded_distribution():
    requests = generate_requests(2718, burst=False, traffic_multiplier=4.0)
    by_class = {name: [r["duration"] for r in requests if r["class"] == name] for name in ("interactive", "batch")}
    assert min(by_class["interactive"]) >= 2 and max(by_class["interactive"]) <= 8
    assert min(by_class["batch"]) >= 5 and max(by_class["batch"]) <= 30
    assert abs(sum(by_class["interactive"]) / len(by_class["interactive"]) - 5) < 0.25
    assert abs(sum(by_class["batch"]) / len(by_class["batch"]) - 16.667) < 0.5
    factors = _workload_gpu_minutes_per_request()
    assert 7.4 < factors["interactive"] < 7.6
    assert 49.8 < factors["batch"] < 50.2


def test_traffic_profiles_are_seeded_scaled_and_default_remains_normal():
    low = generate_requests(2026, burst=False, traffic_multiplier=0.5)
    normal = generate_requests(2026, burst=False)
    high = generate_requests(2026, burst=False, traffic_multiplier=2.0)
    assert low == generate_requests(2026, burst=False, traffic_multiplier=0.5)
    assert high == generate_requests(2026, burst=False, traffic_multiplier=2.0)
    assert normal == generate_requests(2026, burst=False, traffic_multiplier=1.0)
    assert len(low) < len(normal) < len(high)
    rates_low = _arrival_rate_forecasts([], generator_rate_multiplier=0.5)
    rates_normal = _arrival_rate_forecasts([])
    assert rates_low[0] == {name: value * 0.5 for name, value in rates_normal[0].items()}
    assert _arrival_rate_forecasts([], generator_prior=False, generator_rate_multiplier=2.0)[0] == {
        name: 0.0 for name in rates_normal[0]}


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
    assert _projected_active_capacity(nodes, 4, 8) == 16  # warm is dispatchable immediately
    assert _projected_active_capacity(nodes, 5, 8) == 24
    assert _projected_active_capacity(nodes, 19, 8) == 24
    assert _projected_active_capacity(nodes, 20, 8) == 32  # cold boot completes in 20 min
    nodes[3].purpose = "warm_stock"
    assert _warm_stock_pipeline_nodes(nodes) == 2  # activating capacity does not count as available warm stock
    _ensure_warm_reserve(nodes, target_warm=3)
    assert [node.state for node in nodes].count("booting") == 2
    assert _warm_stock_pipeline_nodes(nodes) == 3
    assert [node.state for node in nodes].count("warm") == 1
    assert [node.state for node in nodes].count("off") == 0


def test_wait_aware_forecast_uses_new_arrivals_only_and_rounded_duration_survival():
    factors = _workload_gpu_minutes_per_request()
    assert abs(sum(_rounded_duration_distribution("interactive").values()) - 1.0) < 1e-9
    rates = {"interactive": 0.5, "batch": 0.0}
    forecast = _expected_future_arrival_concurrency(rates, 600, 50, factors)
    assert forecast[0] == 0  # current known work is accounted separately
    assert forecast[1] > 0 and forecast[10] > forecast[1]
    assert forecast[50] >= 0
    assert _expected_future_arrival_concurrency(rates, 1438, 10, factors)[10] == 0


def test_forecast_replay_does_not_expose_hidden_future_trace_arrivals():
    prefix = [{"id": "early", "class": "interactive", "arrival": 20,
               "gpus": 2, "duration": 10, "latency": 2}]
    future = [{"id": f"later-{i}", "class": "batch", "arrival": 500,
               "gpus": 4, "duration": 15, "latency": 30} for i in range(12)]
    base = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8, "request_trace": prefix,
                                   "flexible_jobs": []})
    extended = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8, "request_trace": prefix + future,
                                       "flexible_jobs": []})
    first_frames = base["policies"]["forecast"]["replay"]["frames"]
    second_frames = extended["policies"]["forecast"]["replay"]["frames"]
    assert first_frames[:500] == second_frames[:500]


def test_readiness_planner_preserves_one_ready_warm_and_keeps_cold_start_honest():
    warm_case = [Node("active"), Node("warm"), Node("off")]
    demand = [8.0] * 51
    demand[5] = 16.0
    plan = _plan_active_readiness(warm_case, demand, 8)
    assert plan["warm_nodes_started"] == 0
    assert plan["cold_nodes_started"] == 0
    assert warm_case[1].state == "warm" and warm_case[1].remaining == 0
    assert plan["projected_active_gpus"][4] == 8
    assert plan["projected_active_gpus"][5] == 8
    assert plan["readiness_gaps_gpus"][5] == 8  # reserve remains ready for a real-time arrival

    cold_case = [Node("active"), Node("off")]
    cold_demand = [8.0] * 51
    cold_demand[25] = 16.0
    cold = _plan_active_readiness(cold_case, cold_demand, 8)
    assert cold["cold_nodes_started"] == 1
    assert cold_case[1].state == "booting" and cold_case[1].remaining == 20
    assert cold["projected_active_gpus"][19] == 8
    assert cold["projected_active_gpus"][20] == 16

    constrained = _plan_active_readiness([Node("active")], [16.0] * 51, 8)
    assert constrained["peak_readiness_gap_gpus"] == 8
    assert constrained["readiness_gap_minutes"] == 51


def test_forecast_margin_uses_matured_error_then_labeled_assumption_fallback():
    margin, source = _forecast_margin([], 80, 0.15, 4)
    assert margin == 12
    assert source == "manual_assumption_fallback"
    margin, source = _forecast_margin([0, 2, 10] * 10, 80, 0.15, 4)
    assert margin == 10
    assert source == "matured_synthetic_window_q95"


def test_warm_node_activation_is_immediate_and_cold_boot_stays_delayed():
    nodes = [Node("active"), Node("warm"), Node("off")]
    _scale_up(nodes, target_active=2, gpn=8)
    assert [node.state for node in nodes] == ["active", "active", "off"]
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
    assert cold[0].state == "active" and cold[0].remaining == 0


def test_realtime_request_promotes_ready_warm_in_arrival_minute_and_replenishes_pipeline():
    trace = [
        {"id": "fill-active", "class": "interactive", "arrival": 5, "gpus": 24, "duration": 20},
        {"id": "use-warm", "class": "interactive", "arrival": 6, "gpus": 8, "duration": 5},
    ]
    result = run_dynamic_comparison({"nodes": 6, "gpus_per_node": 8, "request_trace": trace,
                                     "flexible_jobs": [], "warm_overhead_nodes": 1,
                                     "min_active_fraction": 0})
    replay = result["policies"]["forecast"]["replay"]
    request = next(row for row in replay["requests"] if row["id"] == "use-warm")
    before, served = replay["frames"][5], replay["frames"][6]
    assert before["states"].count("warm") >= 1
    assert request["started_at_minute"] == 6
    assert served["states"].count("active") > before["states"].count("active")
    assert served["warm_ready_capacity_gpus"] == served["states"].count("warm") * 8
    assert served["dispatchable_capacity_gpus"] >= served["active_spare_gpus"]
    assert result["policies"]["forecast"]["metrics"]["requests_waited"] == 0
    assert replay["frames"][7]["warm_reserve_booting_nodes"] >= 1


def test_zero_warm_target_does_not_seed_unrequested_standby_nodes():
    result = run_dynamic_comparison({"nodes": 4, "gpus_per_node": 8, "request_trace": [],
                                     "flexible_jobs": [], "warm_overhead_nodes": 0,
                                     "min_active_fraction": 0})
    frame = result["policies"]["forecast"]["replay"]["frames"][0]
    assert frame["warm_reserve_ready_nodes"] == 0
    assert frame["warm_stock_target_nodes"] == 0


def test_hourly_grid_cost_breakdown_reconciles_to_total_and_tariff_periods():
    result = run_dynamic_comparison({"nodes": 8, "gpus_per_node": 8, "bursts": False, "flexible_jobs": []})
    policy = result["policies"]["forecast"]
    rows = policy["hourly_grid_costs"]
    assert len(rows) == 24
    assert [row["tariff_period"] for row in rows[:8]] == ["valley"] * 8
    assert rows[10]["tariff_period"] == "peak" and rows[21]["tariff_period"] == "peak"
    assert rows[22]["tariff_period"] == "flat"
    assert abs(sum(row["cost_cny"] for row in rows) - policy["metrics"]["cost_cny"]) < 0.0005
    assert abs(sum(row["grid_kwh"] for row in rows) - policy["metrics"]["grid_kwh"]) < 0.0005


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


def test_headroom_inventory_is_fixed_and_warm_overhead_is_separate_from_formula_target():
    result = run_dynamic_comparison({"seed": 2026, "nodes": 48, "headroom_nodes": 16,
                                    "gpus_per_node": 8, "traffic_profile": "high",
                                    "bursts": False, "warm_overhead_nodes": 1,
                                    "min_active_fraction": 0.5, "trace_source": "legacy"})
    assert result["base_nodes"] == 48 and result["headroom_nodes"] == 16
    assert result["nodes"] == 64 and result["fleet_gpus"] == 512
    assert result["headroom_nodes"] == 16
    offered_totals = {policy["metrics"]["offered_gpu_minutes"] for policy in result["policies"].values()}
    assert len(offered_totals) == 1
    snapshot = result["realized_peak_snapshot"]
    assert sum(snapshot[key] for key in ("active_nodes", "warm_ready_nodes", "booting_nodes", "warming_nodes", "off_nodes")) == 64
    assert snapshot["offered_gpus"] > 0
    assert snapshot["active_nodes"] < 64
    assert snapshot["off_nodes"] + snapshot["warm_ready_nodes"] + snapshot["booting_nodes"] + snapshot["warming_nodes"] > 0
    assert snapshot["warm_stock_target_nodes"] == 1
    assert result["policies"]["forecast"]["metrics"]["requests_waited_by_class"].keys() == {"interactive", "batch"}
    forecast_frames = result["policies"]["forecast"]["replay"]["frames"]
    assert all(frame["warm_stock_target_nodes"] == 1 for frame in forecast_frames)
    assert any(frame["warm_reserve_ready_nodes"] >= 1 for frame in forecast_frames)


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
    assert set(body["policies"]) == {"always_on", "reactive", "forecast", "forecast_v2"}
    assert body["selected_policy"] == "forecast_v2"
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


def test_traffic_presets_change_one_shared_trace_and_keep_explicit_trace_unchanged():
    normal = run_dynamic_comparison({"seed": 2026, "nodes": 8, "gpus_per_node": 8, "bursts": False})
    default = run_dynamic_comparison({"seed": 2026, "nodes": 8, "gpus_per_node": 8, "bursts": False,
                                      "traffic_profile": "normal"})
    low = run_dynamic_comparison({"seed": 2026, "nodes": 8, "gpus_per_node": 8, "bursts": False,
                                  "traffic_profile": "low"})
    high = run_dynamic_comparison({"seed": 2026, "nodes": 8, "gpus_per_node": 8, "bursts": False,
                                   "traffic_profile": "high"})
    assert normal["requests_generated"] == default["requests_generated"]
    assert low["requests_generated"] < normal["requests_generated"] < high["requests_generated"]
    assert high["offered_peak_gpus"] > low["offered_peak_gpus"]
    for result in (low, normal, high):
        metrics = [policy["metrics"] for policy in result["policies"].values()]
        assert len({item["offered_gpu_minutes"] for item in metrics}) == 1
        fingerprints = {
            key: [(row["id"], row["tier"], row["arrival_minute"], row["gpus"], row["duration_minutes"])
                  for row in policy["replay"]["requests"]]
            for key, policy in result["policies"].items()
        }
        assert fingerprints["always_on"] == fingerprints["reactive"] == fingerprints["forecast"]
    trace = [{"id": "explicit", "class": "interactive", "arrival": 0, "gpus": 2, "duration": 5}]
    explicit = run_dynamic_comparison({"nodes": 4, "gpus_per_node": 8, "request_trace": trace,
                                       "traffic_profile": "high", "flexible_jobs": []})
    assert explicit["requests_generated"] == 1
    assert explicit["traffic_multiplier"] is None
    assert "not applied" in explicit["traffic_profile_description"]
    explicit_request = explicit["policies"]["forecast"]["replay"]["requests"][0]
    assert (explicit_request["id"], explicit_request["tier"], explicit_request["arrival_minute"],
            explicit_request["gpus"], explicit_request["duration_minutes"]) == (
                "explicit", "interactive", 0, 2, 5)


def test_replay_node_workload_breakdown_matches_placements_and_marks_mixed_node():
    trace = [{"id": "rt", "class": "interactive", "arrival": 0, "gpus": 4, "duration": 5}]
    flexible = [{"id": "flex", "name": "Flexible training", "arrival": 0,
                 "deadline": 2, "gpu_hours": 20, "max_gpus": 20, "tier": "pro"}]
    result = run_dynamic_comparison({"nodes": 12, "gpus_per_node": 8, "request_trace": trace,
                                     "flexible_jobs": flexible})
    frames = result["policies"]["forecast"]["replay"]["frames"]
    frame = next(item for item in frames if sum(item["realtime_used_gpus"]) and sum(item["flexible_used_gpus"]))
    assert sum(frame["realtime_used_gpus"]) == 4
    assert 0 < sum(frame["flexible_used_gpus"]) <= 20
    assert frame["used_gpus"] == [r + f for r, f in zip(frame["realtime_used_gpus"], frame["flexible_used_gpus"])]
    assert any(r > 0 and f > 0 for r, f in zip(frame["realtime_used_gpus"], frame["flexible_used_gpus"]))
    for item in frames:
        active_capacity = sum(state == "active" for state in item["states"]) * 8
        occupied = sum(item["realtime_used_gpus"]) + sum(item["flexible_used_gpus"])
        assert item["active_capacity_gpus"] == active_capacity
        assert item["active_spare_gpus"] == max(0.0, round(active_capacity - occupied, 3))
        assert item["warm_reserve_ready_nodes"] == sum(state == "warm" for state in item["states"])
        for used, realtime, flex in zip(item["used_gpus"], item["realtime_used_gpus"], item["flexible_used_gpus"]):
            assert abs(used - realtime - flex) <= 0.001


def test_default_forecast_01_to_02_has_idle_active_reserve_and_no_observed_wait():
    result = run_dynamic_comparison({"trace_source": "legacy", "seed": 2026, "nodes": 32,
                                     "gpus_per_node": 8, "traffic_profile": "normal"})
    forecast = result["policies"]["forecast"]
    replay = forecast["replay"]
    frames = replay["frames"]
    interval_frames = frames[60:120]
    interval_requests = [
        request for request in replay["requests"]
        if 60 <= request["arrival_minute"] < 120
    ]

    assert result["requests_generated"] == 2109
    assert result["nodes"] == 32
    assert result["headroom_nodes"] == 0
    assert len(interval_requests) == 30
    assert all(request["started_at_minute"] == request["arrival_minute"] for request in interval_requests)
    assert forecast["metrics"]["requests_waited"] == 0
    assert forecast["metrics"]["requests_queued_at_horizon"] == 0
    assert min(frame["active_spare_gpus"] for frame in interval_frames) > 0
    assert all(frame["active_spare_gpus"] > 0 for frame in interval_frames)

    # At 01:10 both configured warm nodes are genuinely ready. The active idle
    # reserve is separate, and observed demand has not waited.
    at_0110 = frames[70]
    assert at_0110["warm_reserve_ready_nodes"] == 2
    assert at_0110["warm_stock_target_nodes"] == 2
    assert at_0110["active_spare_gpus"] == 28.0
    assert at_0110["dispatchable_capacity_gpus"] == 44.0
    assert at_0110["readiness_capacity_shortfall_gpus"] == 0.0
    assert at_0110["forecast_capacity_shortfall_gpus"] == 0.0
    assert frames[75]["warm_reserve_ready_nodes"] >= 1


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
