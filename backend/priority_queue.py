"""Deterministic, non-preemptive real-time request priority simulation."""

from __future__ import annotations

import heapq
import math
from typing import Any

from .data import build_case

MAX_REQUESTS = 32
MAX_ARRIVAL_MINUTE = 119
MAX_DURATION_MINUTES = 120
MAX_GPU_COUNT = 512
TIERS = {"pro", "standard"}


def _whole_number(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.") from None
    if not math.isfinite(number) or not number.is_integer() or number < low or number > high:
        raise ValueError(f"{label} must be a whole number between {low} and {high}.")
    return int(number)


def validate_requests(requests: Any, capacity_gpus: int) -> list[dict[str, Any]]:
    if not isinstance(requests, list):
        raise ValueError("Requests must be provided as a list.")
    if len(requests) > MAX_REQUESTS:
        raise ValueError(f"Use at most {MAX_REQUESTS} requests per simulation.")

    normalized = []
    seen_ids: set[str] = set()
    for position, item in enumerate(requests):
        if not isinstance(item, dict):
            raise ValueError(f"Request {position + 1} must be an object.")
        request_id = item.get("id", f"request-{position + 1}")
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 64:
            raise ValueError(f"Request {position + 1} needs a short, non-empty ID.")
        request_id = request_id.strip()
        if request_id in seen_ids:
            raise ValueError(f"Request ID {request_id} is duplicated.")
        seen_ids.add(request_id)
        tier = item.get("tier", "standard")
        if not isinstance(tier, str) or tier.lower() not in TIERS:
            raise ValueError(f"Tier for {request_id} must be Pro or Standard.")
        normalized.append({
            "id": request_id,
            "name": str(item.get("name", request_id))[:80],
            "tier": tier.lower(),
            "arrival_minute": _whole_number(item.get("arrival_minute", 0), f"Arrival for {request_id}", 0, MAX_ARRIVAL_MINUTE),
            "gpu_count": _whole_number(item.get("gpu_count"), f"GPU demand for {request_id}", 1, MAX_GPU_COUNT),
            "duration_minutes": _whole_number(item.get("duration_minutes"), f"Duration for {request_id}", 1, MAX_DURATION_MINUTES),
            "sequence": position,
        })
    return normalized


def simulate_request_queue(
    requests: Any,
    *,
    scenario: str = "baseline",
    gpu_count: int = 256,
    hour: int = 12,
) -> dict[str, Any]:
    """Replay requests against the real-time GPU reservation in one selected hour.

    At each event time, completed requests are released, new arrivals enter the
    queue, then dispatch picks the earliest fitting Pro request. Standard can
    start only when no queued Pro request fits the currently free GPUs. An
    earlier oversized request may be skipped for another fitting request in
    its tier (bounded backfill); each tier remains FIFO among requests eligible
    to start. Running requests are never interrupted.
    """
    chosen_hour = _whole_number(hour, "Selected hour", 0, 23)
    case = build_case({"scenario": scenario, "gpu_count": gpu_count})
    capacity = int(case["realtime_gpus"][chosen_hour])
    normalized = validate_requests(requests, capacity)

    statuses = {}
    arrivals: dict[int, list[dict[str, Any]]] = {}
    for request in normalized:
        if request["gpu_count"] > capacity:
            statuses[request["id"]] = {
                **request,
                "status": "rejected",
                "reason": f"Needs {request['gpu_count']} GPUs, above this hour's {capacity}-GPU real-time reservation.",
            }
        else:
            arrivals.setdefault(request["arrival_minute"], []).append(request)
            statuses[request["id"]] = {**request, "status": "not arrived"}

    # Heap keys express the promised priority: Pro tier first, FIFO by arrival,
    # then insertion order for exact arrival ties.
    waiting: list[tuple[int, int, int, str]] = []
    running: dict[str, dict[str, Any]] = {}
    completed: list[str] = []
    timeline = []
    next_arrival_times = sorted(arrivals)
    minute = 0

    while next_arrival_times or running or waiting:
        possible_times = []
        if next_arrival_times:
            possible_times.append(next_arrival_times[0])
        if running:
            possible_times.append(min(entry["ends_at_minute"] for entry in running.values()))
        if not possible_times:
            break
        minute = max(minute, min(possible_times))
        events = []

        for request_id, entry in list(running.items()):
            if entry["ends_at_minute"] <= minute:
                released = entry["gpu_count"]
                del running[request_id]
                completed.append(request_id)
                statuses[request_id]["status"] = "completed"
                statuses[request_id]["completed_at_minute"] = minute
                events.append({"type": "completed", "request_id": request_id, "name": entry["name"], "gpu_count": released})

        if next_arrival_times and next_arrival_times[0] == minute:
            next_arrival_times.pop(0)
            for request in arrivals[minute]:
                priority = 0 if request["tier"] == "pro" else 1
                heapq.heappush(waiting, (priority, request["arrival_minute"], request["sequence"], request["id"]))
                statuses[request["id"]]["status"] = "waiting"
                events.append({"type": "arrived", "request_id": request["id"], "name": request["name"], "tier": request["tier"]})

        while waiting:
            free_gpus = capacity - sum(entry["gpu_count"] for entry in running.values())
            selected = next((item for item in sorted(waiting) if statuses[item[3]]["gpu_count"] <= free_gpus), None)
            if selected is None:
                break
            # Remove exactly the selected next-fitting request; re-heapify so
            # the priority/FIFO order of all other candidates is preserved.
            eligible_index = waiting.index(selected)
            waiting[eligible_index] = waiting[-1]
            waiting.pop()
            if eligible_index < len(waiting):
                heapq.heapify(waiting)
            _, _, _, request_id = selected
            request = statuses[request_id]
            ends_at = minute + request["duration_minutes"]
            request.update({
                "status": "running",
                "started_at_minute": minute,
                "ends_at_minute": ends_at,
                "wait_minutes": minute - request["arrival_minute"],
            })
            running[request_id] = {"name": request["name"], "gpu_count": request["gpu_count"], "ends_at_minute": ends_at}
            events.append({"type": "started", "request_id": request_id, "name": request["name"], "tier": request["tier"], "gpu_count": request["gpu_count"], "ends_at_minute": ends_at})

        timeline.append({
            "minute": minute,
            "events": events,
            "waiting_order": [item[3] for item in sorted(waiting)],
            "running": [
                {"request_id": request_id, **entry}
                for request_id, entry in sorted(running.items(), key=lambda pair: (statuses[pair[0]]["started_at_minute"], statuses[pair[0]]["sequence"]))
            ],
            "completed": list(completed),
            "free_gpus": capacity - sum(entry["gpu_count"] for entry in running.values()),
        })

    return {
        "scenario": case["scenario_label"],
        "selected_hour": chosen_hour,
        "capacity_gpus": capacity,
        "realtime_gpus_by_hour": list(case["realtime_gpus"]),
        "requests": [
            {key: value for key, value in statuses[request["id"]].items() if key != "sequence"}
            for request in normalized
        ],
        "timeline": timeline,
        "policy": {
            "pro_priority": "A queued Pro request starts before any queued Standard request that fits the same free capacity.",
            "within_tier": "FIFO by arrival minute, then insertion order; the next fitting request may backfill past an oversized waiting request.",
            "preemption": "Running requests are never interrupted.",
            "reservation": "Uses the selected hour's fixed real-time GPU reservation; these requests are not added to the flexible-job energy model again.",
            "meaning": "Deterministic queue simulation for synthetic requests; not inference execution or a measured service-level objective.",
        },
    }
