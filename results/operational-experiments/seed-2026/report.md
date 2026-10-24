# GridShift operational simulation experiment report

The objective-analysis sections below are calculated from this saved report's recorded simulator metrics using the current API's documented rule; the source scenario output was not regenerated as part of this documentation update.

- Seeds: 2026
- Scenarios: normal_day, demand_burst, constrained_fleet
- Simulation status: synthetic and illustrative; these are not measured infrastructure results or service guarantees.
- Controller comparisons come from one simulator invocation per seed/scenario, which evaluates all supported controllers against the same request trace and flexible schedule.
- Canonical scheduled-versus-unscheduled percentages are taken from the simulator response. Formula: `(unscheduled baseline − scheduled result) / unscheduled baseline × 100`; negative values mean increases. Percent savings are shown only when the simulator says service outcomes are comparable.
- The unscheduled baseline is all-nodes-active, immediate FIFO/ASAP work without energy scheduling. The existing `always_on` controller remains flexible-LP scheduled; it is not the unscheduled baseline.
- The older scheduled-controller cost diagnostic remains separately labeled; its percentage is shown only when request terminal statuses and flexible-work outcomes match. Latency metrics are shown separately.
- Missing metrics are shown as unavailable (—), never as zero. Renewable inputs are the simulator's fixed synthetic profile; no renewable override is supported.

## Input provenance

- Data status: synthetic_illustrative_not_measurements
- Demand: seeded Poisson requests; 5-minute arrivals; triangular service durations; optional hidden 3x bursts
- IT power assumptions: `{"active_node_idle": 1.0, "boot_node": 1.2, "busy_gpu_increment": 0.35, "fixed_site_overhead": 18.0, "warm_node": 0.25}`; PUE 1.25.
- Tariff: Oct 2026 Fujian 1–10(20) kV State Grid agent-purchase single-part proxy; not this user's verified Xiamen tariff ([source](https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm)).
- Grid carbon: 0.55 kg CO2/kWh East-China annual-average proxy; not hourly marginal emissions or CO2e ([source](https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html)).

## normal_day · seed 2026

Seeded normal one-day request trace; hidden burst generation disabled.

Configuration: `{"bursts": false, "forecast_alpha": 0.3, "gpus_per_node": 8, "margin_fraction": 0.15, "min_active_fraction": 0.25, "nodes": 32, "request_count": 2044, "request_trace_source": "backend.dynamic_simulation.generate_requests(seed, burst=False)"}`

**Selected policy (Forecast) vs Always-on FIFO / ASAP (no energy scheduling):** facility electricity 6.24% reduction (3074.657 → 2882.959 kWh); grid imports 7.48% reduction (2562.657 → 2370.959 kWh); cost 8.71% reduction (1504.581 → 1373.519 CNY); operational emissions 7.48% reduction (1409.462 → 1304.028 kg CO₂).

Unscheduled baseline: **Always-on FIFO / ASAP (no energy scheduling)** (all nodes active; immediate FIFO/ASAP work; no energy scheduling).

### Energy and cost comparison

Percentages below use the simulator's canonical unscheduled-baseline comparisons. A blank percentage means the API omitted it, the denominator was zero/unavailable, or service equivalence failed.

| Result | Status | Facility electricity kWh | Facility reduction % | Grid import kWh | Grid reduction % | Cost CNY | Cost reduction % | Emissions kg CO₂ | Emissions reduction % | Service comparable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| Always-on FIFO / ASAP (no energy scheduling) | complete | 3074.657 | — | 2562.657 | — | 1504.581 | — | 1409.462 | — | baseline |
| Always On | complete | 3074.657 | 0 | 2562.657 | 0 | 1506.142 | -0.104 | 1409.462 | 0 | True |
| Reactive | complete | 2875.032 | 6.493 | 2363.032 | 7.79 | 1367.897 | 9.085 | 1299.668 | 7.79 | True |
| Forecast | complete | 2882.959 | 6.235 | 2370.959 | 7.48 | 1373.519 | 8.711 | 1304.028 | 7.48 | True |

### Three-objective candidate frontier

Using facility electricity, proxy cost, and operational grid emissions together, Reactive is the sole Pareto candidate and individual minimum for all three metrics in this run. All four candidates have matching terminal request outcomes and flexible-work delivery/deadline outcomes; latency differences remain separate above. The frontier covers this synthetic scenario only, not a global optimum.

The tolerance is `max(0.001 metric units, 1e-9 × max magnitude)`. “Service-comparable” here means matching terminal/flexible outcomes to the baseline, not an SLA guarantee.

| Candidate | Status | Facility kWh | Cost CNY | Grid kg CO₂ | Individual minimum |
|---|---|---:|---:|---:|---|
| Unscheduled baseline | Dominated | 3074.657 | 1504.581 | 1409.462 | — |
| Always On | Dominated | 3074.657 | 1506.142 | 1409.462 | — |
| Reactive | Pareto frontier | 2875.032 | 1367.897 | 1299.668 | Facility, cost, emissions |
| Forecast | Dominated | 2882.959 | 1373.519 | 1304.028 | — |

### Scheduled-controller diagnostic

This retains the earlier comparison among LP-scheduled controllers; `always_on` here is not the no-scheduling baseline.

| Scheduled controller | Cost CNY | Cost delta vs scheduled always-on | Request terminal outcomes match? |
|---|---:|---:|:---:|
| Always On | 1506.142 | +0.000 CNY (+0.00%) | always-on reference |
| Reactive | 1367.897 | +138.245 CNY (+9.18%) | yes |
| Forecast | 1373.519 | +132.623 CNY (+8.81%) | yes |

### Service performance

| Result | Completed | Queued at horizon | Running at horizon | Rejected | Mean / P95 wait min | Mean completion latency min | Flex admission | Flex delivered / unmet GPU-h | Flex deadlines met | Service note |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| Always-on FIFO / ASAP (no energy scheduling) | 2037 | 0 | 7 | 0 | 5.57 / 39 | 12.67 | admitted | 3060 / 0 | 6 / 6 | — |
| Always On | 2037 | 0 | 7 | 0 | 0 / 0 | 7.1 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Reactive | 2037 | 0 | 7 | 0 | 0 / 0 | 7.1 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Forecast | 2037 | 0 | 7 | 0 | 0 / 0 | 7.1 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |

The scheduled `always_on` row uses the existing flexible-job LP and remains separate from the no-scheduling baseline.
The legacy `cost_change_cny_vs_always_on` and `cost_savings_pct_vs_always_on` columns in `summary.csv` are diagnostic comparisons among scheduled controllers only.
Queue/wait, flexible-work, fleet/forecast shortfalls, node-state minutes and raw simulator-reported canonical percentages are available in `summary.csv`.

- always_on vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.

## demand_burst · seed 2026

Normal seeded trace plus 80 simultaneous synthetic 4-GPU requests at minute 720 (320 offered GPUs).

Configuration: `{"burst_arrival_minute": 720, "burst_duration_minutes": 2, "burst_gpus_per_request": 4, "burst_request_count": 80, "burst_total_gpus": 320, "bursts": false, "forecast_alpha": 0.3, "gpus_per_node": 8, "margin_fraction": 0.15, "min_active_fraction": 0.25, "nodes": 32, "request_count": 2124, "request_trace_source": "backend.dynamic_simulation.generate_requests(seed, burst=False)"}`

**Selected policy (Forecast) vs Always-on FIFO / ASAP (no energy scheduling):** facility electricity 6.18% reduction (3079.324 → 2888.881 kWh); grid imports 7.42% reduction (2567.324 → 2376.881 kWh); cost 8.62% reduction (1507.483 → 1377.501 CNY); operational emissions 7.42% reduction (1412.028 → 1307.285 kg CO₂).

Unscheduled baseline: **Always-on FIFO / ASAP (no energy scheduling)** (all nodes active; immediate FIFO/ASAP work; no energy scheduling).

### Energy and cost comparison

Percentages below use the simulator's canonical unscheduled-baseline comparisons. A blank percentage means the API omitted it, the denominator was zero/unavailable, or service equivalence failed.

| Result | Status | Facility electricity kWh | Facility reduction % | Grid import kWh | Grid reduction % | Cost CNY | Cost reduction % | Emissions kg CO₂ | Emissions reduction % | Service comparable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| Always-on FIFO / ASAP (no energy scheduling) | complete | 3079.324 | — | 2567.324 | — | 1507.483 | — | 1412.028 | — | baseline |
| Always On | complete | 3079.324 | 0 | 2567.324 | 0 | 1509.044 | -0.104 | 1412.028 | 0 | True |
| Reactive | complete | 2879.699 | 6.483 | 2367.699 | 7.776 | 1370.799 | 9.067 | 1302.234 | 7.776 | True |
| Forecast | complete | 2888.881 | 6.185 | 2376.881 | 7.418 | 1377.501 | 8.622 | 1307.285 | 7.418 | True |

### Three-objective candidate frontier

Reactive is the sole Pareto candidate and individual minimum for facility electricity, proxy cost, and operational grid emissions among these four service-comparable results. This is the frontier for this synthetic burst case only, not a global optimum.

The tolerance is `max(0.001 metric units, 1e-9 × max magnitude)`. “Service-comparable” means matching terminal/flexible outcomes to the baseline, not an SLA guarantee.

| Candidate | Status | Facility kWh | Cost CNY | Grid kg CO₂ | Individual minimum |
|---|---|---:|---:|---:|---|
| Unscheduled baseline | Dominated | 3079.324 | 1507.483 | 1412.028 | — |
| Always On | Dominated | 3079.324 | 1509.044 | 1412.028 | — |
| Reactive | Pareto frontier | 2879.699 | 1370.799 | 1302.234 | Facility, cost, emissions |
| Forecast | Dominated | 2888.881 | 1377.501 | 1307.285 | — |

### Scheduled-controller diagnostic

This retains the earlier comparison among LP-scheduled controllers; `always_on` here is not the no-scheduling baseline.

| Scheduled controller | Cost CNY | Cost delta vs scheduled always-on | Request terminal outcomes match? |
|---|---:|---:|:---:|
| Always On | 1509.044 | +0.000 CNY (+0.00%) | always-on reference |
| Reactive | 1370.799 | +138.245 CNY (+9.16%) | yes |
| Forecast | 1377.501 | +131.543 CNY (+8.72%) | yes |

### Service performance

| Result | Completed | Queued at horizon | Running at horizon | Rejected | Mean / P95 wait min | Mean completion latency min | Flex admission | Flex delivered / unmet GPU-h | Flex deadlines met | Service note |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| Always-on FIFO / ASAP (no energy scheduling) | 2117 | 0 | 7 | 0 | 8.96 / 58 | 15.87 | admitted | 3060 / 0 | 6 / 6 | — |
| Always On | 2117 | 0 | 7 | 0 | 0.21 / 0 | 7.12 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Reactive | 2117 | 0 | 7 | 0 | 0.21 / 0 | 7.12 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Forecast | 2117 | 0 | 7 | 0 | 0.21 / 0 | 7.12 | admitted | 3060 / 0 | 6 / 6 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |

The scheduled `always_on` row uses the existing flexible-job LP and remains separate from the no-scheduling baseline.
The legacy `cost_change_cny_vs_always_on` and `cost_savings_pct_vs_always_on` columns in `summary.csv` are diagnostic comparisons among scheduled controllers only.
Queue/wait, flexible-work, fleet/forecast shortfalls, node-state minutes and raw simulator-reported canonical percentages are available in `summary.csv`.

- always_on vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.

## constrained_fleet · seed 2026

Eight-GPU fleet with 16 simultaneous synthetic 8-GPU batch requests; flexible LP admission may be infeasible.

Configuration: `{"arrival_minute": 0, "bursts": false, "duration_minutes": 180, "forecast_alpha": 0.3, "gpus_per_node": 4, "gpus_per_request": 8, "margin_fraction": 0.15, "min_active_fraction": 0.25, "nodes": 2, "request_count": 16, "request_trace_source": "fixed controlled overload trace"}`

**Selected policy (Forecast) vs Always-on FIFO / ASAP (no energy scheduling):** facility electricity 0.00% change (684 → 684 kWh); grid imports 0.00% change (398 → 398 kWh); cost 0.00% change (220.565 → 220.565 CNY); operational emissions 0.00% change (218.9 → 218.9 kg CO₂).

Unscheduled baseline: **Always-on FIFO / ASAP (no energy scheduling)** (all nodes active; immediate FIFO/ASAP work; no energy scheduling).

### Energy and cost comparison

Percentages below use the simulator's canonical unscheduled-baseline comparisons. A blank percentage means the API omitted it, the denominator was zero/unavailable, or service equivalence failed.

| Result | Status | Facility electricity kWh | Facility reduction % | Grid import kWh | Grid reduction % | Cost CNY | Cost reduction % | Emissions kg CO₂ | Emissions reduction % | Service comparable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| Always-on FIFO / ASAP (no energy scheduling) | complete | 684 | — | 398 | — | 220.565 | — | 218.9 | — | baseline |
| Always On | complete | 684 | 0 | 398 | 0 | 220.565 | 0 | 218.9 | 0 | True |
| Reactive | complete | 684 | 0 | 398 | 0 | 220.565 | 0 | 218.9 | 0 | True |
| Forecast | complete | 684 | 0 | 398 | 0 | 220.565 | 0 | 218.9 | 0 | True |

### Three-objective candidate frontier

All four candidates are tied on the three energy/cost/emissions metrics and are non-dominated within tolerance. Every tied candidate is an individual minimum for all three metrics. The shared results do not indicate a unique policy advantage; this is only the frontier for the constrained synthetic case.

The tolerance is `max(0.001 metric units, 1e-9 × max magnitude)`. “Service-comparable” means matching terminal/flexible outcomes to the baseline, not an SLA guarantee.

| Candidate | Status | Facility kWh | Cost CNY | Grid kg CO₂ | Individual minimum |
|---|---|---:|---:|---:|---|
| Unscheduled baseline | Pareto frontier | 684 | 220.565 | 218.9 | Facility, cost, emissions |
| Always On | Pareto frontier | 684 | 220.565 | 218.9 | Facility, cost, emissions |
| Reactive | Pareto frontier | 684 | 220.565 | 218.9 | Facility, cost, emissions |
| Forecast | Pareto frontier | 684 | 220.565 | 218.9 | Facility, cost, emissions |

### Scheduled-controller diagnostic

This retains the earlier comparison among LP-scheduled controllers; `always_on` here is not the no-scheduling baseline.

| Scheduled controller | Cost CNY | Cost delta vs scheduled always-on | Request terminal outcomes match? |
|---|---:|---:|:---:|
| Always On | 220.565 | +0.000 CNY (+0.00%) | always-on reference |
| Reactive | 220.565 | +0.000 CNY (+0.00%) | yes |
| Forecast | 220.565 | +0.000 CNY (+0.00%) | yes |

### Service performance

| Result | Completed | Queued at horizon | Running at horizon | Rejected | Mean / P95 wait min | Mean completion latency min | Flex admission | Flex delivered / unmet GPU-h | Flex deadlines met | Service note |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| Always-on FIFO / ASAP (no energy scheduling) | 7 | 8 | 1 | 0 | 540 / 1080 | 720 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 / 3060 | 0 / 0 | — |
| Always On | 7 | 8 | 1 | 0 | 540 / 1080 | 720 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 / 3060 | 0 / 0 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Reactive | 7 | 8 | 1 | 0 | 540 / 1080 | 720 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 / 3060 | 0 / 0 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |
| Forecast | 7 | 8 | 1 | 0 | 540 / 1080 | 720 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 / 3060 | 0 / 0 | Same request terminal states and flexible-job inputs, admission, delivered work, and deadline outcomes; wait/completion-latency differences remain reported separately. |

The scheduled `always_on` row uses the existing flexible-job LP and remains separate from the no-scheduling baseline.
The legacy `cost_change_cny_vs_always_on` and `cost_savings_pct_vs_always_on` columns in `summary.csv` are diagnostic comparisons among scheduled controllers only.
Queue/wait, flexible-work, fleet/forecast shortfalls, node-state minutes and raw simulator-reported canonical percentages are available in `summary.csv`.

- always_on vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast vs scheduled always-on diagnostic: Same request and flexible-work outcomes; latency metrics remain visible separately.
