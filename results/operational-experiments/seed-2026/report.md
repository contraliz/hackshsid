# GridShift operational simulation experiment report

- Seeds: 2026
- Scenarios: normal_day, demand_burst, constrained_fleet
- Simulation status: synthetic and illustrative; these are not measured infrastructure results or service guarantees.
- Controller comparisons come from one simulator invocation per seed/scenario, which evaluates all supported controllers against the same request trace and flexible schedule.
- Cost savings are shown only when request terminal statuses and flexible-work outcomes match the always-on baseline. Latency metrics are shown separately.
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

| Controller | Status | Completed | Queued at horizon | Rejected | Flex admission | Flex deadlines met | Facility kWh | Grid kWh | Renewable used kWh | Cost CNY | Emissions kg CO₂ | Cost change vs always-on |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| always_on | complete | 2037 | 0 | 0 | admitted | 6 | 3074.657 | 2562.657 | 512 | 1506.142 | 1409.462 | +0.000 CNY (+0.00%) |
| reactive | complete | 2037 | 0 | 0 | admitted | 6 | 2875.032 | 2363.032 | 512 | 1367.897 | 1299.668 | +138.245 CNY (+9.18%) |
| forecast | complete | 2037 | 0 | 0 | admitted | 6 | 2875.032 | 2363.032 | 512 | 1367.897 | 1299.668 | +138.245 CNY (+9.18%) |

Queue/wait, flexible delivered/unmet GPU-hours, fleet and forecast shortfalls, and node-state minutes are in `summary.csv`.
Cost change is `always_on cost − controller cost`; positive values mean lower modeled cost only when the note says outcomes match.

- always_on comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.

## demand_burst · seed 2026

Normal seeded trace plus 80 simultaneous synthetic 4-GPU requests at minute 720 (320 offered GPUs).

Configuration: `{"burst_arrival_minute": 720, "burst_duration_minutes": 2, "burst_gpus_per_request": 4, "burst_request_count": 80, "burst_total_gpus": 320, "bursts": false, "forecast_alpha": 0.3, "gpus_per_node": 8, "margin_fraction": 0.15, "min_active_fraction": 0.25, "nodes": 32, "request_count": 2124, "request_trace_source": "backend.dynamic_simulation.generate_requests(seed, burst=False)"}`

| Controller | Status | Completed | Queued at horizon | Rejected | Flex admission | Flex deadlines met | Facility kWh | Grid kWh | Renewable used kWh | Cost CNY | Emissions kg CO₂ | Cost change vs always-on |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| always_on | complete | 2117 | 0 | 0 | admitted | 6 | 3079.324 | 2567.324 | 512 | 1509.044 | 1412.028 | +0.000 CNY (+0.00%) |
| reactive | complete | 2117 | 0 | 0 | admitted | 6 | 2879.699 | 2367.699 | 512 | 1370.799 | 1302.234 | +138.245 CNY (+9.16%) |
| forecast | complete | 2117 | 0 | 0 | admitted | 6 | 2879.699 | 2367.699 | 512 | 1370.799 | 1302.234 | +138.245 CNY (+9.16%) |

Queue/wait, flexible delivered/unmet GPU-hours, fleet and forecast shortfalls, and node-state minutes are in `summary.csv`.
Cost change is `always_on cost − controller cost`; positive values mean lower modeled cost only when the note says outcomes match.

- always_on comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.

## constrained_fleet · seed 2026

Eight-GPU fleet with 16 simultaneous synthetic 8-GPU batch requests; flexible LP admission may be infeasible.

Configuration: `{"arrival_minute": 0, "bursts": false, "duration_minutes": 180, "forecast_alpha": 0.3, "gpus_per_node": 4, "gpus_per_request": 8, "margin_fraction": 0.15, "min_active_fraction": 0.25, "nodes": 2, "request_count": 16, "request_trace_source": "fixed controlled overload trace"}`

| Controller | Status | Completed | Queued at horizon | Rejected | Flex admission | Flex deadlines met | Facility kWh | Grid kWh | Renewable used kWh | Cost CNY | Emissions kg CO₂ | Cost change vs always-on |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| always_on | complete | 7 | 8 | 0 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 | 684 | 398 | 286 | 220.565 | 218.9 | +0.000 CNY (+0.00%) |
| reactive | complete | 7 | 8 | 0 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 | 684 | 398 | 286 | 220.565 | 218.9 | +0.000 CNY (+0.00%) |
| forecast | complete | 7 | 8 | 0 | infeasible: Total GPUs (8) must cover the maximum reserved real-time demand (88 GPUs). | 0 | 684 | 398 | 286 | 220.565 | 218.9 | +0.000 CNY (+0.00%) |

Queue/wait, flexible delivered/unmet GPU-hours, fleet and forecast shortfalls, and node-state minutes are in `summary.csv`.
Cost change is `always_on cost − controller cost`; positive values mean lower modeled cost only when the note says outcomes match.

- always_on comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- reactive comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
- forecast comparison: Same request and flexible-work outcomes; latency metrics remain visible separately.
