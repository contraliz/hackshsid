# Dynamic simulation receipt — seed 2026

Generated 2026-10-24 with `backend.dynamic_simulation.run_dynamic_comparison`. The 32×8 run used one seeded 2,109-request trace and the same fixed hourly Pro-priority LP schedule (six flexible jobs, 3,060 GPU-hours) across all three node policies. All figures are synthetic model output, not measurements or deployment predictions. The default trace had a peak unconstrained offered concurrency of 107 GPUs. All 3,060 flexible GPU-hours ran by their deadlines in every policy. Each policy completed 2,102 requests; seven were running at the 24-hour horizon and none were rejected. Offered and served request work was 33,028 GPU-minutes. The `energy_accounted_gpu_minutes` metric also includes the 183,600 flexible GPU-minutes delivered, for 216,628 total GPU-minutes counted in variable GPU power.

| Policy | Facility kWh | Grid kWh | Renewable used / curtailed kWh | CNY proxy cost* | Grid CO₂ kg** | Requests completed / running at horizon | Flexible work scheduled / delivered / unmet GPU·h | Flexible deadlines met |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Always-on | 3,079.579 | 2,567.579 | 512.000 / 0 | 1,510.261 | 1,412.169 | 2,102 / 7 | 3,060 / 3,060 / 0 | 6 / 6 |
| Reactive | 2,883.626 | 2,371.626 | 512.000 / 0 | 1,374.940 | 1,304.394 | 2,102 / 7 | 3,060 / 3,060 / 0 | 6 / 6 |
| Forecast reserve | 2,883.626 | 2,371.626 | 512.000 / 0 | 1,374.940 | 1,304.394 | 2,102 / 7 | 3,060 / 3,060 / 0 | 6 / 6 |

Reactive and forecast are numerically identical on this seed. Their energy/cost reduction versus always-on is a synthetic result for this one trace and fixed schedule; it does not establish a generally superior policy. Request mean completion latency was 7.10 minutes and 486 of 2,102 completed requests met the illustrative response allowance under all three policies. Those allowances are diagnostics, not SLAs. No flexible commitment GPU-minutes were missed. The contemporaneous forecast-capacity check reports zero fleet shortfall for this 32×8 trace; maxima from different forecast/reservation minutes are not added together.

The 12×8 (96-GPU) illustrative preset produced an LP admission result of **infeasible** for the default six-job workload (3,060 GPU-hours) under the hourly real-time reservation curve. The UI reports all six candidates as not admitted and 3,060 GPU-hours unmet; it does not claim that this preset ran the default flexible workload. Request-only results still show the trace peak exceeded the 96-GPU fleet by 11 GPUs for 4 minutes, while the uncalibrated forecast margin did not predict a fleet shortfall. Therefore, the 96-GPU request-only energy numbers are not a like-for-like comparison with the 256-GPU accepted-flex case.

A focused feasible test used a custom 20-GPU-hour Pro job with a two-hour deadline plus a same-input burst trace of twenty simultaneous 8-GPU, 30-minute requests on a 96-GPU fleet. All three controllers delivered all 20 GPU-hours by deadline, had zero flexible-commitment shortfall, and completed all 20 requests; requests waited rather than taking protected capacity. A separate 100-GPU-hour, one-hour job was reported LP-infeasible and not admitted.

*Cost uses the published October 2026 State Grid Fujian 1–10(20) kV single-part agent-purchase curve as a CNY proxy. This is not a verified Xiamen customer's tariff or eligibility. [Official October 2026 table hosted by Dehua County Government](https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm).

**Grid CO₂ uses the official 2023 East-China annual average, 0.5500 kgCO₂/kWh; this is not hourly marginal emissions or CO₂e. [MEE/NBS announcement](https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html).

Reproduce the default run from the repository root:

```powershell
.\.venv\Scripts\python.exe -c "from backend.dynamic_simulation import run_dynamic_comparison; r=run_dynamic_comparison({'seed':2026,'nodes':32,'gpus_per_node':8}); print({k:v['metrics'] for k,v in r['policies'].items()})"
```

The full policy, model variables, assumptions, official tariff evidence, flexible admission/commitment rules, and remaining limitations are documented in [`notes/model-specification.md`](../notes/model-specification.md).
