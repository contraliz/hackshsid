"""Realistic-shaped synthetic request traffic for the GridShift replay.

This generator is *not* a fitted production trace. It is a deliberately
heavier-tailed, over-dispersed, autocorrelated replacement for the original
uniform-Poisson demo so that queueing, startup latency and forecasting error
actually occur. The shape is motivated by published cluster traces:

* request sizes and durations are heavy-tailed (Borg, MLaaS-in-the-Wild),
  not uniform draws from a 1-2 GPU / 2-8 minute box;
* arrivals are over-dispersed and autocorrelated minute to minute, so traffic
  arrives in bursts and lulls rather than as independent Poisson noise;
* the class mix shifts across the day (interactive share rises during working
  hours, batch/cron work dominates at night);
* a small fraction of jobs are long "stragglers" that occupy capacity for
  hours, which is what makes queueing interesting.

Everything is seeded and deterministic. Nothing here is measured data.

Design knobs (all at module level so experiments can be reproduced):
  BASE_TOTAL_PER_MIN   peak-rate scale for all classes combined
  FAST_PHI / FAST_SIG  minute-scale multiplicative traffic noise
  SLOW_PHI / SLOW_SIG  multi-hour demand regime shifts
  STRAGGLER_SHARE      fraction of jobs multiplied by STRAGGLER_FACTOR
"""
from __future__ import annotations

import math
import random
from typing import Any

MINUTES_PER_DAY = 24 * 60
BUCKET = 5

# --- traffic intensity -------------------------------------------------------
# Total requests/minute before class split, interpolated smoothly (cosine)
# between knots. Two peaks (late morning, evening) and a deep night trough.
PROFILE_KNOTS = [
    (0.0, 0.18), (5.0, 0.14), (6.5, 0.30), (8.0, 0.78), (9.5, 1.00),
    (11.5, 1.05), (13.0, 0.86), (15.0, 1.00), (17.0, 1.12), (19.0, 1.30),
    (21.0, 1.05), (22.5, 0.66), (24.0, 0.28),
]
BASE_TOTAL_PER_MIN = 2.0

FAST_PHI, FAST_SIG = 0.97, 0.11
SLOW_PHI, SLOW_SIG = 0.998, 0.012

# Fraction of arrivals that are interactive by hour of day.
INTERACTIVE_SHARE_KNOTS = [
    (0.0, 0.42), (7.0, 0.48), (9.0, 0.72), (18.0, 0.70),
    (21.0, 0.58), (24.0, 0.44),
]

SIZE_INTERACTIVE = [(1, 0.82), (2, 0.13), (4, 0.04), (8, 0.01)]
BATCH_SIZE_MEDIAN = 4.0
BATCH_SIZE_SIGMA = 0.9
GANG_SHARE = 0.05
GANG_RANGE = (16, 64)

DUR_INTERACTIVE_MEDIAN = 4.0
DUR_INTERACTIVE_SIGMA = 0.9
DUR_BATCH_MEDIAN = 16.0
DUR_BATCH_SIGMA = 1.0
STRAGGLER_SHARE = 0.015
STRAGGLER_FACTOR = 4.0

LATENCY = {"interactive": 2, "batch": 30}


def _interp(knots: list[tuple[float, float]], hour: float) -> float:
    """Cosine-interpolate a piecewise profile; avoids visible step changes."""
    if hour <= knots[0][0]:
        return knots[0][1]
    for (h0, v0), (h1, v1) in zip(knots, knots[1:]):
        if hour <= h1:
            span = max(h1 - h0, 1e-9)
            weight = 0.5 - 0.5 * math.cos(math.pi * (hour - h0) / span)
            return v0 + (v1 - v0) * weight
    return knots[-1][1]


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return median * math.exp(sigma * rng.gauss(0.0, 1.0))


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    limit, product, count = math.exp(-mean), 1.0, 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _batch_size(rng: random.Random, fleet_gpus: int) -> int:
    if rng.random() < GANG_SHARE:
        size = rng.randint(*GANG_RANGE)
    else:
        size = round(_lognormal(rng, BATCH_SIZE_MEDIAN, BATCH_SIZE_SIGMA))
    return max(1, min(fleet_gpus, size))


def _interactive_size(rng: random.Random, fleet_gpus: int) -> int:
    draw, cumulative = rng.random(), 0.0
    for size, probability in SIZE_INTERACTIVE:
        cumulative += probability
        if draw <= cumulative:
            return max(1, min(fleet_gpus, size))
    return 1


def _duration(rng: random.Random, name: str) -> int:
    if name == "interactive":
        value = _lognormal(rng, DUR_INTERACTIVE_MEDIAN, DUR_INTERACTIVE_SIGMA)
    else:
        value = _lognormal(rng, DUR_BATCH_MEDIAN, DUR_BATCH_SIGMA)
    if rng.random() < STRAGGLER_SHARE:
        value *= STRAGGLER_FACTOR
    return max(1, min(MINUTES_PER_DAY, round(value)))


def generate_realistic_requests(seed: int, *, traffic_multiplier: float = 1.0,
                                gpus_per_node: int = 8, nodes: int = 32) -> list[dict[str, Any]]:
    """Generate one seeded day of heavy-tailed, bursty requests."""
    if traffic_multiplier <= 0 or not math.isfinite(traffic_multiplier):
        raise ValueError("Traffic multiplier must be a positive finite number.")
    rng = random.Random(seed)
    fleet_gpus = max(1, int(gpus_per_node) * int(nodes))

    # Two autoregressive multiplicative factors: a minute-scale burst process
    # and a slow demand-regime process. Both are mean-corrected so the
    # expected intensity equals the profile.
    fast = slow = 0.0
    fast_var = FAST_SIG ** 2 / max(1e-9, 1.0 - FAST_PHI ** 2)
    slow_var = SLOW_SIG ** 2 / max(1e-9, 1.0 - SLOW_PHI ** 2)

    records: list[dict[str, Any]] = []
    for minute in range(MINUTES_PER_DAY):
        fast = FAST_PHI * fast + FAST_SIG * rng.gauss(0.0, 1.0)
        slow = SLOW_PHI * slow + SLOW_SIG * rng.gauss(0.0, 1.0)
        hour = minute / 60.0
        intensity = (_interp(PROFILE_KNOTS, hour) * BASE_TOTAL_PER_MIN
                     * traffic_multiplier
                     * math.exp(fast + slow - 0.5 * (fast_var + slow_var)))
        total = _poisson(rng, max(0.0, intensity))
        if not total:
            continue
        share = _interp(INTERACTIVE_SHARE_KNOTS, hour)
        for _ in range(total):
            name = "interactive" if rng.random() < share else "batch"
            gpus = (_interactive_size(rng, fleet_gpus) if name == "interactive"
                    else _batch_size(rng, fleet_gpus))
            records.append({
                "id": f"{name}-{len(records)}",
                "class": name,
                "arrival": minute,
                "gpus": gpus,
                "duration": _duration(rng, name),
                "latency": LATENCY[name],
            })
    return sorted(records, key=lambda r: (r["arrival"], r["id"]))
