import pytest

from backend.data import build_case
from backend.priority_queue import simulate_request_queue
from backend.scheduler import asap_baseline, evaluate_schedule, run_comparison, solve_lp


def test_default_case_is_deterministic_and_optimizer_is_feasible():
    first = build_case({})
    second = build_case({})
    assert first == second
    result = run_comparison({})
    repeat = run_comparison({})
    assert result["optimizer"]["status"] == "Optimal"
    assert result["optimizer"]["validation"]["passed"] is True
    assert result["optimized"]["metrics"]["all_deadlines_met"] is True
    assert result["optimized"]["metrics"] == repeat["optimized"]["metrics"]


def test_dispatch_respects_windows_parallelism_capacity_and_energy_balance():
    result = run_comparison({})
    case = result["case"]
    schedule = result["optimizer"]["schedule_gpu_hours"]
    assert all(value >= -1e-8 for row in schedule for value in row)
    for job_index, job in enumerate(case["jobs"]):
        assert sum(schedule[job_index]) == pytest.approx(job["gpu_hours"], abs=1e-6)
        for hour, amount in enumerate(schedule[job_index]):
            if hour < job["arrival"] or hour >= job["deadline"]:
                assert amount == pytest.approx(0, abs=1e-8)
            assert amount <= job["max_gpus"] * case["slot_hours"] + 1e-6
    hourly = result["optimized"]["hourly"]
    for hour in range(24):
        assert hourly["total_gpus"][hour] <= case["gpu_count"] + 1e-6
        assert hourly["renewable_used_kwh"][hour] <= case["renewable_available_kwh"][hour] + 1e-6
        assert (
            hourly["grid_import_kwh"][hour] + hourly["renewable_used_kwh"][hour]
        ) == pytest.approx(hourly["load_kwh"][hour], abs=1e-6)


def test_baseline_and_optimizer_use_the_same_accounting_function():
    case = build_case({})
    schedule, _ = asap_baseline(case)
    evaluated = evaluate_schedule(case, schedule)
    result = run_comparison({})
    assert result["baseline"]["metrics"] == evaluated["metrics"]


def test_zero_renewable_availability_keeps_energy_balance():
    case = build_case({"renewable_scale": 0})
    result = solve_lp(case)
    assert result["status"] == "Optimal"
    assert sum(result["hourly"]["renewable_used_kwh"]) == pytest.approx(0, abs=1e-8)
    for hour in range(24):
        assert result["hourly"]["grid_import_kwh"][hour] == pytest.approx(
            result["hourly"]["load_kwh"][hour], abs=1e-6
        )


def test_impossible_demand_is_reported_as_infeasible_not_relaxed():
    result = run_comparison({"scenario": "demand-surge"})
    assert result["optimizer"]["status"] == "Infeasible"
    assert result["optimizer"]["success"] is False
    assert result["optimized"] is None
    assert result["baseline"]["metrics"]["flexible_gpu_hours_unmet"] > 0


def test_invalid_gpu_reservation_is_a_clear_input_error():
    with pytest.raises(ValueError, match="must cover the maximum reserved real-time demand"):
        build_case({"gpu_count": 48})


def test_carbon_weight_changes_objective_without_changing_workload():
    low = build_case({"carbon_weight": 0})
    high = build_case({"carbon_weight": 0.8})
    assert [job["gpu_hours"] for job in low["jobs"]] == [job["gpu_hours"] for job in high["jobs"]]
    assert solve_lp(low)["status"] == "Optimal"
    assert solve_lp(high)["status"] == "Optimal"
    low_result = run_comparison({"carbon_weight": 0})
    high_result = run_comparison({"carbon_weight": 0.8})
    assert high_result["optimized"]["metrics"]["grid_emissions_kg_co2e"] < low_result["optimized"]["metrics"]["grid_emissions_kg_co2e"]


def test_optimizer_moves_flexible_work_into_the_cheapest_eligible_hour():
    case = build_case({"renewable_scale": 0, "carbon_weight": 0})
    case["jobs"] = [{"id": "single", "name": "Single job", "arrival": 0, "deadline": 24, "gpu_hours": 4, "max_gpus": 4}]
    case["price_cost_units_per_kwh"] = [0.8] * 24
    case["price_cost_units_per_kwh"][3] = 0.1
    case["grid_carbon_kg_per_kwh"] = [0.4] * 24
    result = solve_lp(case)
    assert result["status"] == "Optimal"
    assert result["schedule_gpu_hours"][0][3] == pytest.approx(4, abs=1e-6)
    assert sum(result["schedule_gpu_hours"][0]) == pytest.approx(4, abs=1e-6)


def test_price_and_renewable_scenario_controls_change_only_their_profile():
    baseline = build_case({})
    price_spike = build_case({"scenario": "price-spike"})
    shortage = build_case({"scenario": "renewables-shortage"})
    assert price_spike["price_cost_units_per_kwh"][18] > baseline["price_cost_units_per_kwh"][18]
    assert price_spike["renewable_available_kwh"] == baseline["renewable_available_kwh"]
    assert shortage["renewable_available_kwh"][12] < baseline["renewable_available_kwh"][12]
    assert shortage["price_cost_units_per_kwh"] == baseline["price_cost_units_per_kwh"]


def test_flask_api_returns_computed_results_and_infeasibility_status():
    from server import app

    client = app.test_client()
    ok = client.post("/api/schedule", json={})
    assert ok.status_code == 200
    assert ok.get_json()["optimizer"]["status"] == "Optimal"
    infeasible = client.post("/api/schedule", json={"scenario": "demand-surge"})
    assert infeasible.status_code == 200
    assert infeasible.get_json()["optimizer"]["status"] == "Infeasible"
    invalid = client.post("/api/schedule", json={"carbon_weight": 9})
    assert invalid.status_code == 422


def _priority_timing_case():
    case = build_case({"gpu_count": 100, "carbon_weight": 0, "renewable_scale": 0})
    case["realtime_gpus"] = [40] * 24
    case["active_equivalent_realtime_gpus"] = [40] * 24
    case["jobs"] = [
        {"id": "pro", "name": "Pro", "arrival": 0, "deadline": 4, "gpu_hours": 10, "max_gpus": 10, "tier": "pro"},
        {"id": "standard", "name": "Standard", "arrival": 0, "deadline": 4, "gpu_hours": 10, "max_gpus": 10, "tier": "standard"},
    ]
    case["price_cost_units_per_kwh"] = [1.0] * 24
    case["price_cost_units_per_kwh"][1:4] = [0.01, 0.02, 0.03]
    case["grid_carbon_kg_per_kwh"] = [0.0] * 24
    return case


def test_pro_earliness_is_lexicographic_and_standard_deadlines_stay_hard():
    case = _priority_timing_case()
    priority = solve_lp(case)
    assert priority["status"] == "Optimal"
    assert priority["validation"]["passed"] is True
    assert priority["jobs"][0]["average_execution_hour"] < priority["jobs"][1]["average_execution_hour"]
    assert priority["jobs"][0]["average_execution_hour"] == pytest.approx(0, abs=1e-6)
    assert all(job["deadline_met"] for job in priority["jobs"])

    case["jobs"][0]["tier"] = "standard"
    cost_only = solve_lp(case)
    assert cost_only["status"] == "Optimal"
    assert cost_only["metrics"]["grid_cost_units"] < priority["metrics"]["grid_cost_units"]


def test_infeasible_standard_deadline_is_not_relaxed_for_pro():
    case = _priority_timing_case()
    case["jobs"][1]["deadline"] = 1
    case["jobs"][0]["deadline"] = 1
    case["gpu_count"] = 50
    case["realtime_gpus"] = [40] * 24
    case["active_equivalent_realtime_gpus"] = [40] * 24
    case["jobs"][0]["gpu_hours"] = 10
    case["jobs"][1]["gpu_hours"] = 10
    # Only ten flexible GPU-hours fit in hour zero, so both hard completions cannot hold.
    result = solve_lp(case)
    assert result["status"] == "Infeasible"
    assert result["success"] is False
    assert "schedule_gpu_hours" not in result


def test_real_time_queue_priority_waiting_fifo_and_non_preemption():
    requests = [
        {"id": "std-long", "tier": "standard", "arrival_minute": 0, "gpu_count": 50, "duration_minutes": 20},
        {"id": "std-small", "tier": "standard", "arrival_minute": 0, "gpu_count": 20, "duration_minutes": 8},
        {"id": "pro-1", "tier": "pro", "arrival_minute": 1, "gpu_count": 20, "duration_minutes": 6},
        {"id": "pro-2", "tier": "pro", "arrival_minute": 2, "gpu_count": 20, "duration_minutes": 4},
        {"id": "std-later", "tier": "standard", "arrival_minute": 5, "gpu_count": 25, "duration_minutes": 5},
    ]
    first = simulate_request_queue(requests, hour=12)
    second = simulate_request_queue(requests, hour=12)
    assert first["timeline"] == second["timeline"]
    by_id = {request["id"]: request for request in first["requests"]}
    assert by_id["std-long"]["started_at_minute"] == 0
    assert by_id["pro-1"]["started_at_minute"] == 8
    assert by_id["pro-2"]["started_at_minute"] == 14
    assert by_id["std-later"]["started_at_minute"] >= by_id["pro-1"]["started_at_minute"]
    # Already-running Standard work isn't interrupted when Pro arrives at minute 1.
    assert by_id["std-long"]["completed_at_minute"] == 20
    assert first["capacity_gpus"] == 72


def test_real_time_backfill_future_arrival_oversize_and_validation():
    requests = [
        {"id": "std-running", "tier": "standard", "arrival_minute": 0, "gpu_count": 50, "duration_minutes": 10},
        {"id": "pro-blocked", "tier": "pro", "arrival_minute": 1, "gpu_count": 50, "duration_minutes": 5},
        {"id": "std-backfill", "tier": "standard", "arrival_minute": 2, "gpu_count": 20, "duration_minutes": 4},
        {"id": "future", "tier": "pro", "arrival_minute": 30, "gpu_count": 10, "duration_minutes": 2},
        {"id": "too-large", "tier": "pro", "arrival_minute": 4, "gpu_count": 73, "duration_minutes": 2},
    ]
    result = simulate_request_queue(requests, hour=12)
    by_id = {request["id"]: request for request in result["requests"]}
    assert by_id["std-backfill"]["started_at_minute"] == 2
    assert by_id["pro-blocked"]["started_at_minute"] == 10
    assert by_id["future"]["started_at_minute"] == 30
    assert by_id["too-large"]["status"] == "rejected"
    assert "above this hour's 72-GPU" in by_id["too-large"]["reason"]

    with pytest.raises(ValueError, match="must be a whole number"):
        simulate_request_queue([{"id": "bad", "tier": "pro", "arrival_minute": 0, "gpu_count": True, "duration_minutes": 2}])
    with pytest.raises(ValueError, match="duplicated"):
        simulate_request_queue([
            {"id": "same", "gpu_count": 5, "duration_minutes": 1},
            {"id": "same", "gpu_count": 5, "duration_minutes": 1},
        ])


def test_real_time_queue_api_is_stateless_and_rejects_invalid_requests():
    from server import app

    client = app.test_client()
    payload = {"hour": 12, "requests": [
        {"id": "std", "tier": "standard", "arrival_minute": 0, "gpu_count": 50, "duration_minutes": 20},
        {"id": "pro", "tier": "pro", "arrival_minute": 1, "gpu_count": 20, "duration_minutes": 4},
    ]}
    first = client.post("/api/realtime-queue", json=payload)
    second = client.post("/api/realtime-queue", json=payload)
    assert first.status_code == 200
    assert first.get_json()["timeline"] == second.get_json()["timeline"]
    assert first.get_json()["capacity_gpus"] == 72
    invalid = client.post("/api/realtime-queue", json={"hour": 99, "requests": []})
    assert invalid.status_code == 422
