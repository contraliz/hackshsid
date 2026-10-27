"""Information-restricted online demand forecaster (v2).

Why this exists
---------------
The original forecaster reads values a real controller cannot know:

* the *true* remaining runtime of every running request (``job["end"]``);
* the *true* duration of every queued request (drawn at arrival);
* the hourly rate vector produced by the whole-day flexible LP;
* the generator's own time-of-day curve and duration distribution, and a
  first-bucket rate seeded from the generator.

This module is a draft replacement that only sees what a scheduler would
observe at time ``t``:

* arrivals that already happened (class, GPU count, minute);
* requests currently running (class, GPU count, age) — **no end minute**;
* requests currently queued (class, GPU count, arrival) — **no duration**;
* its own node states and remaining boot timers;
* its own admitted flexible commitments (remaining GPU-minutes, deadline);
* completions it has observed (lifetime = now - start).

Everything else is estimated online:

1. **Time-of-day intensity.** 48 half-hour slots per class, each shrunk
   toward the running global rate with a pseudo-count prior, multiplied by a
   short-horizon EWMA deviation factor so regime shifts and bursts are picked
   up within minutes.
2. **Service time.** Kaplan-Meier survival per class from completed lifetimes
   plus right-censored ages of still-running jobs. Running jobs contribute
   ``S(age+h)/S(age)`` instead of a known end minute; queued jobs contribute
   an expected duration instead of their true duration.
3. **Load.** New-arrival concurrency is ``sum_a lambda(t+a) * E[G] * S(h-a)``;
   running load uses residual survival; queued jobs are packed at their
   earliest feasible slot; flexible work is spread as the minimum average
   rate needed to hit its deadline.
4. **Uncertainty.** Split-conformal style: the controller records the
   residual of every issued forecast once the minute is observed and takes an
   online 90th percentile per horizon bucket. Before enough residuals exist it
   falls back to ``max(4 GPUs, 20% of predicted)``.

This is a draft, not a validated production forecaster.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
import math
from typing import Iterable

HORIZON = 40
BUCKET = 5
SLOT_MINUTES = 30
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES

PRIOR_RATE_PER_MIN = 1.0
PRIOR_GPUS = {"interactive": 1.5, "batch": 6.0}
PRIOR_DURATION = {"interactive": 8.0, "batch": 40.0}
PRIOR_WEIGHT = 8.0

RECENT_ALPHA = 0.08
RECENT_CLIP = (0.35, 3.5)

CONFIDENCE = 0.92
MIN_RESIDUALS = 24
MAX_RESIDUALS = 240
MAX_SURVIVAL_MINUTES = 600
MAX_MEAN_WINDOW = 240
SURVIVAL_PRIOR_WEIGHT = 20.0
MAX_QUEUE_JOBS = 48
MAX_QUEUE_DURATION = 45


@dataclass(frozen=True)
class RunningJob:
    """A running request as the controller can see it: no end minute."""
    class_name: str
    gpus: int
    age_minutes: int


@dataclass(frozen=True)
class QueuedJob:
    """A queued request as the controller can see it: no duration."""
    class_name: str
    gpus: int
    arrival_minute: int
    request_id: str = ""


@dataclass(frozen=True)
class NodeView:
    state: str
    remaining_minutes: int = 0


@dataclass(frozen=True)
class FlexCommitment:
    """The controller's own accepted flexible work."""
    remaining_gpu_minutes: float
    minutes_to_deadline: int
    max_gpus: float


@dataclass
class ForecastResult:
    predicted_by_offset: list[float]
    upper_by_offset: list[float]
    new_arrivals_by_offset: list[float]
    running_by_offset: list[float]
    queue_by_offset: list[float]
    flex_by_offset: list[float]
    margin_gpus: float
    margin_source: str
    residual_samples: int
    unplaced_queue_jobs: int
    margins_by_bucket: list[float] = field(default_factory=list)


class ForecasterV2:
    """Online forecaster that never receives hidden simulation fields."""

    def __init__(self, gpus_per_node: int, fleet_nodes: int,
                 warm_start_minutes: int = 0, cold_start_minutes: int = 20):
        self.gpus_per_node = max(1, int(gpus_per_node))
        self.fleet_nodes = max(1, int(fleet_nodes))
        self.warm_start = max(0, int(warm_start_minutes))
        self.cold_start = max(0, int(cold_start_minutes))

        self.slot_events = {name: [0] * SLOTS_PER_DAY for name in PRIOR_GPUS}
        self.slot_minutes = {name: [0] * SLOTS_PER_DAY for name in PRIOR_GPUS}
        self.total_events = {name: 0 for name in PRIOR_GPUS}
        self.total_minutes = {name: 0 for name in PRIOR_GPUS}
        self.gpu_sum = {name: 0.0 for name in PRIOR_GPUS}
        self.gpu_count = {name: 0 for name in PRIOR_GPUS}
        self.completed = {name: deque(maxlen=4000) for name in PRIOR_GPUS}
        self.recent_ratio = {name: 1.0 for name in PRIOR_GPUS}
        self.arrivals_this_minute = {name: 0 for name in PRIOR_GPUS}
        self.residuals = [deque(maxlen=MAX_RESIDUALS) for _ in range(HORIZON // BUCKET + 1)]
        self.pending: list[tuple[int, list[float]]] = []
        self.survival_cache: dict[str, list[float]] = {}
        self.survival_key: dict[str, tuple] = {}
        self.censored_ages: dict[str, list[int]] = {name: [] for name in PRIOR_GPUS}

    # ------------------------------------------------------------------ input
    def observe_arrival(self, minute: int, class_name: str, gpus: int) -> None:
        if class_name not in self.slot_events:
            return
        slot = (minute % (24 * 60)) // SLOT_MINUTES
        self.slot_events[class_name][slot] += 1
        self.total_events[class_name] += 1
        self.gpu_sum[class_name] += float(gpus)
        self.gpu_count[class_name] += 1
        self.arrivals_this_minute[class_name] += 1

    def observe_completion_for(self, class_name: str, lifetime_minutes: int) -> None:
        if class_name in self.completed and lifetime_minutes > 0:
            self.completed[class_name].append(int(lifetime_minutes))

    def observe_minute(self, minute: int, arrivals_by_class: dict[str, int]) -> None:
        """Advance the clock: update slot denominators and the recent-deviation EWMA."""
        slot = (minute % (24 * 60)) // SLOT_MINUTES
        for name in self.slot_events:
            self.slot_minutes[name][slot] += 1
            self.total_minutes[name] += 1
            expected = self._slot_rate(name, slot)
            observed = arrivals_by_class.get(name, 0)
            ratio = observed / expected if expected > 1e-9 else 1.0
            ratio = min(RECENT_CLIP[1], max(RECENT_CLIP[0], ratio))
            self.recent_ratio[name] = (1 - RECENT_ALPHA) * self.recent_ratio[name] + RECENT_ALPHA * ratio
            self.arrivals_this_minute[name] = 0
        self._expire_pending(minute)

    # ------------------------------------------------------------- estimation
    def _global_rate(self, name: str) -> float:
        events = self.total_events[name] + PRIOR_WEIGHT * PRIOR_RATE_PER_MIN
        minutes = self.total_minutes[name] + PRIOR_WEIGHT
        return events / max(minutes, 1e-9)

    def _slot_rate(self, name: str, slot: int) -> float:
        """Shrunk per-slot rate; the prior is the running global level."""
        global_rate = self._global_rate(name)
        events = self.slot_events[name][slot] + PRIOR_WEIGHT * global_rate
        minutes = self.slot_minutes[name][slot] + PRIOR_WEIGHT
        return events / max(minutes, 1e-9)

    def _rate_at(self, name: str, minute: int) -> float:
        slot = (minute % (24 * 60)) // SLOT_MINUTES
        return max(0.0, self._slot_rate(name, slot) * self.recent_ratio[name])

    def mean_gpus(self, name: str) -> float:
        count = self.gpu_count[name]
        total = self.gpu_sum[name] + PRIOR_WEIGHT * PRIOR_GPUS[name]
        return total / max(count + PRIOR_WEIGHT, 1e-9)

    def mean_duration(self, name: str) -> float:
        survival = self.survival(name)
        if not survival:
            return PRIOR_DURATION[name]
        return max(1.0, min(MAX_MEAN_WINDOW, sum(survival[:MAX_MEAN_WINDOW])))

    def survival(self, name: str) -> list[float]:
        """Kaplan-Meier survival over completed lifetimes and censored running ages."""
        running_ages = self.censored_ages.get(name, [])
        key = (len(self.completed[name]), len(running_ages), sum(running_ages))
        if self.survival_key.get(name) == key:
            return self.survival_cache[name]
        events = sorted(self.completed[name])
        observations = sorted(list(events) + list(running_ages))
        horizon = MAX_SURVIVAL_MINUTES
        steps: dict[int, float] = {}
        current = 1.0
        index = 0
        while index < len(events):
            time = events[index]
            if time > horizon:
                break
            end = index
            while end < len(events) and events[end] == time:
                end += 1
            at_risk = len(observations) - bisect_left(observations, time)
            if at_risk > 0:
                current *= 1.0 - (end - index) / at_risk
            steps[time] = current
            index = end
        times = sorted(steps)
        empirical = [1.0] * (horizon + 1)
        position, value = 0, 1.0
        for minute in range(horizon + 1):
            while position < len(times) and times[position] <= minute:
                value = steps[times[position]]
                position += 1
            empirical[minute] = value
        # Shrink toward a broad exponential prior until enough lifetimes are seen,
        # so a cold-start controller does not assume every job runs forever.
        observed = len(events) + len(running_ages)
        weight = min(1.0, observed / (observed + SURVIVAL_PRIOR_WEIGHT))
        mean = PRIOR_DURATION[name]
        survival = [weight * empirical[minute] + (1.0 - weight) * math.exp(-minute / mean)
                    for minute in range(horizon + 1)]
        self.survival_cache[name] = survival
        self.survival_key[name] = key
        return survival

    def residual_life(self, name: str, age: int, horizon: int) -> float:
        """E[remaining minutes | already running for ``age``], truncated at ``horizon``."""
        survival = self.survival(name)
        age = max(0, int(age))
        start = survival[min(age, MAX_SURVIVAL_MINUTES)]
        if start <= 1e-9:
            return 0.0
        end = min(MAX_SURVIVAL_MINUTES, age + max(1, horizon))
        return sum(survival[age:end]) / start

    def alive_probability(self, name: str, age: int, offset: int) -> float:
        survival = self.survival(name)
        age = max(0, int(age))
        if age >= MAX_SURVIVAL_MINUTES:
            return 0.0
        denominator = survival[age]
        if denominator <= 1e-9:
            return 0.0
        return survival[min(MAX_SURVIVAL_MINUTES, age + offset)] / denominator

    # -------------------------------------------------------------- forecasting
    def predict(self, minute: int, running: Iterable[RunningJob], queued: Iterable[QueuedJob],
                nodes: Iterable[NodeView], flex: Iterable[FlexCommitment]) -> ForecastResult:
        running = list(running)
        queued = list(queued)
        nodes = list(nodes)
        flex = list(flex)

        self.censored_ages = {name: [] for name in PRIOR_GPUS}
        for job in running:
            if job.class_name in self.censored_ages:
                self.censored_ages[job.class_name].append(max(0, job.age_minutes))
        self.survival_key.clear()

        horizon = HORIZON
        new_arrivals = [0.0] * (horizon + 1)
        for name in self.slot_events:
            mean_gpus = self.mean_gpus(name)
            survival = self.survival(name)
            for offset in range(1, horizon + 1):
                rate = self._rate_at(name, minute + offset)
                if rate <= 0:
                    continue
                base = rate * mean_gpus
                new_arrivals[offset] += base * survival[0]
                for earlier in range(1, offset):
                    new_arrivals[offset] += (self._rate_at(name, minute + earlier) * mean_gpus
                                             * survival[offset - earlier])

        running_load = [0.0] * (horizon + 1)
        for job in running:
            for offset in range(horizon + 1):
                running_load[offset] += job.gpus * self.alive_probability(
                    job.class_name, job.age_minutes, offset)

        available = [self._projected_gpus(nodes, offset) for offset in range(horizon + 1)]
        # Real-time work has dispatch priority, so queue placement sees no flexible load.
        zero_flex = [0.0] * (horizon + 1)
        queue_load, unplaced = self._place_queue(queued, available, running_load, zero_flex,
                                                 new_arrivals, horizon)

        # Flexible work is greedy in the dispatcher: it takes whatever active
        # capacity remains after real-time work, up to each job's parallelism
        # limit. The forecast predicts that policy rather than the LP hourly plan.
        hungry = 0.0
        for job in flex:
            if job.minutes_to_deadline > 0 and job.remaining_gpu_minutes > 0:
                hungry += min(float(job.max_gpus), job.remaining_gpu_minutes)
        flex_load = [0.0] * (horizon + 1)
        for offset in range(horizon + 1):
            realtime = running_load[offset] + new_arrivals[offset] + queue_load[offset]
            spare = max(0.0, available[offset] - realtime)
            flex_load[offset] = min(hungry, spare)

        predicted = [running_load[o] + flex_load[o] + new_arrivals[o] + queue_load[o]
                     for o in range(horizon + 1)]
        upper, margin, source, samples, margins = self._upper_bound(predicted)
        self.pending.append((minute, predicted))
        return ForecastResult(
            predicted_by_offset=predicted,
            upper_by_offset=upper,
            new_arrivals_by_offset=new_arrivals,
            running_by_offset=running_load,
            queue_by_offset=queue_load,
            flex_by_offset=flex_load,
            margin_gpus=margin,
            margin_source=source,
            residual_samples=samples,
            unplaced_queue_jobs=unplaced,
            margins_by_bucket=margins,
        )

    def _projected_gpus(self, nodes: list[NodeView], offset: int) -> float:
        ready = 0
        for node in nodes:
            if node.state == "active":
                ready += 1
            elif node.state == "warming" and node.remaining_minutes <= offset:
                ready += 1
            elif node.state == "warm" and offset >= self.warm_start:
                ready += 1
            elif node.state == "booting" and node.remaining_minutes + self.warm_start <= offset:
                ready += 1
            # OFF nodes are only counted if the controller has actually ordered a boot,
            # which the caller represents as a booting node with a remaining timer.
        return ready * self.gpus_per_node

    def _place_queue(self, queued: list[QueuedJob], available: list[float],
                     running: list[float], flex: list[float], new_arrivals: list[float],
                     horizon: int) -> tuple[list[float], int]:
        load = [0.0] * (horizon + 1)
        ordered = sorted(queued, key=lambda job: (0 if job.class_name == "interactive" else 1,
                                                  job.arrival_minute, job.request_id))[:MAX_QUEUE_JOBS]
        unplaced = 0
        for job in ordered:
            duration = int(max(1, min(MAX_QUEUE_DURATION,
                                      round(self.mean_duration(job.class_name)))))
            placed = False
            for start in range(0, max(1, horizon - duration + 2)):
                fits = True
                for offset in range(start, min(horizon + 1, start + duration)):
                    occupied = running[offset] + flex[offset] + new_arrivals[offset] + load[offset]
                    if available[offset] - occupied + 1e-9 < job.gpus:
                        fits = False
                        break
                if fits:
                    for offset in range(start, min(horizon + 1, start + duration)):
                        load[offset] += job.gpus
                    placed = True
                    break
            if not placed:
                unplaced += 1
        return load, unplaced

    def _upper_bound(self, predicted: list[float]) -> tuple[list[float], float, str, int, list[float]]:
        upper = list(predicted)
        margins: list[float] = []
        samples = sum(len(bucket) for bucket in self.residuals)
        if samples >= MIN_RESIDUALS:
            for offset in range(len(predicted)):
                bucket = min(len(self.residuals) - 1, max(0, (offset - 1) // BUCKET))
                values = self.residuals[bucket]
                if len(values) >= MIN_RESIDUALS:
                    ordered = sorted(values)
                    index = min(len(ordered) - 1, max(0, math.ceil(CONFIDENCE * len(ordered)) - 1))
                    margin = max(4.0, float(ordered[index]))
                else:
                    margin = max(4.0, 0.20 * predicted[offset])
                upper[offset] = predicted[offset] + margin
                margins.append(margin)
            margin = upper[0] - predicted[0]
            return upper, margin, "online_conformal_q90", samples, margins
        for offset in range(len(predicted)):
            fallback = max(4.0, 0.20 * predicted[offset])
            upper[offset] = predicted[offset] + fallback
            margins.append(fallback)
        return upper, upper[0] - predicted[0], "cold_start_fallback", samples, margins

    # ------------------------------------------------------------- calibration
    def score(self, minute: int, observed_demand: float) -> None:
        """Score every issued forecast whose minute has now been observed."""
        keep: list[tuple[int, list[float]]] = []
        for issued_minute, predicted in self.pending:
            offset = minute - issued_minute
            if 1 <= offset <= HORIZON:
                bucket = min(len(self.residuals) - 1, (offset - 1) // BUCKET)
                self.residuals[bucket].append(float(observed_demand) - predicted[offset])
            if offset <= HORIZON:
                keep.append((issued_minute, predicted))
        self.pending = keep

    def _expire_pending(self, minute: int) -> None:
        self.pending = [(issued, predicted) for issued, predicted in self.pending
                        if minute - issued <= HORIZON]

    def diagnostics(self) -> dict[str, object]:
        return {
            "residuals_per_bucket": [len(bucket) for bucket in self.residuals],
            "recent_ratio": {name: round(value, 3) for name, value in self.recent_ratio.items()},
            "mean_gpus": {name: round(self.mean_gpus(name), 3) for name in PRIOR_GPUS},
            "mean_duration_minutes": {name: round(self.mean_duration(name), 2) for name in PRIOR_GPUS},
            "slot_rate_interactive": round(self._slot_rate("interactive", 0), 4),
            "observed_arrivals": dict(self.total_events),
        }
