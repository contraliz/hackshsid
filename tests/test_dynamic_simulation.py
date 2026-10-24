from backend.dynamic_simulation import (
    Node,
    _forecast_series,
    _offered_gpu_trace,
    _scale_up,
    _choose_waiting_request,
    _advance_transitions,
    _ensure_warm_reserve,
    generate_requests,
    run_dynamic_comparison,
)


def test_synthetic_trace_is_seeded_and_forecast_is_causal():
    first = generate_requests(17, burst=False)
    assert first == generate_requests(17, burst=False)
    trace = _offered_gpu_trace(first)
    _, forecast = _forecast_series(trace, alpha=0.3)
    changed_future = list(trace)
    changed_future[500:] = [999] * (len(changed_future) - 500)
    _, forecast_after_change = _forecast_series(changed_future, alpha=0.3)
    assert forecast[:101] == forecast_after_change[:101]


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


def test_batch_aging_prevents_new_work_from_backfilling_an_aged_head():
    from collections import deque

    statuses = {
        "batch-old": {"class": "batch", "arrival": 0, "gpus": 8},
        "interactive-new": {"class": "interactive", "arrival": 16, "gpus": 1},
    }
    waiting = deque(statuses)
    assert _choose_waiting_request(waiting, statuses, minute=16, free_gpus=4) is None
    assert _choose_waiting_request(waiting, statuses, minute=16, free_gpus=8) == "batch-old"
