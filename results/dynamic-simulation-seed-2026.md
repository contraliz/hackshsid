# Dynamic simulation receipt — seed 2026

Generated 2026-10-24 by `backend.dynamic_simulation.run_dynamic_comparison` using the same seeded 2,109-request trace in each policy. Numbers below are synthetic model output, not measurements or deployment predictions. Inventory is the default 32 × 8 = 256 GPUs. The request trace's peak unconstrained offered concurrency was 107 GPUs. All three methods completed 2,102 requests; seven were still running at the 24-hour cutoff; none were rejected. Every method accumulated 33,028 offered and 33,028 served GPU-minutes in this run. Request response allowances are illustrative diagnostics and are not SLAs.

| Policy | Facility kWh | Grid kWh | Renewable used / curtailed kWh | Cost CNY* | Grid CO₂ kg** | Mean / p95 wait min | Mean completion latency min | Response allowances met / completed | Peak active nodes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Always-on | 1,740.829 | 1,232.802 | 508.027 / 3.973 | 742.236 | 678.041 | 0.00 / 0 | 7.10 | 486 / 2,102 | 32 |
| Reactive | 1,032.350 | 644.596 | 387.754 / 124.246 | 382.582 | 354.528 | 0.07 / 0 | 7.17 | 486 / 2,102 | 16 |
| Forecast reserve | 1,032.350 | 644.596 | 387.754 / 124.246 | 382.582 | 354.528 | 0.07 / 0 | 7.17 | 486 / 2,102 | 16 |

The 96-GPU illustrative preset, under the same seed and trace, experienced 11 GPUs of peak offered demand above fleet capacity for 4 minutes under every policy; peak forecast shortfall stayed at 0 GPUs, showing the uncalibrated EWMA/margin did not anticipate that realized peak. All policies completed 2,102 requests by cutoff, with seven still running and no rejections. Dynamic control changed service timing: reactive and forecast each met 470 of 2,102 illustrative response allowances versus 486 for always-on. This is a forecast/overload limitation, not a guarantee of adequate 96-GPU capacity.

For the 256-GPU default case, the two dynamic policies reduce modeled facility energy and cost versus always-on while the completed-request and illustrative response-allowance counts are equal; mean completion latency rises by 0.07 minutes. Reactive and forecast are numerically identical on this seed. In the 96-GPU case, dynamic control raises p95 wait to 2 minutes and reduces the response-allowance count from 486 to 470. Forecast meets the same service metrics as reactive but uses slightly more modeled facility energy/cost in this seed. No policy is selected as universally preferable from one synthetic trace. This one-day workload is too small to calibrate the forecast.

*Cost uses the published October 2026 State Grid Fujian 1–10(20) kV single-part agent-purchase curve as a province-level proxy. It is not a verified Xiamen customer's tariff or eligibility. [Official October 2026 table hosted by Dehua County Government](https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm).

**Grid CO₂ uses the official 2023 East-China annual average, 0.5500 kgCO₂/kWh; it is not hourly marginal emissions or CO₂e. [MEE/NBS announcement](https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html).

Reproduce the run from the repository root:

```powershell
.\.venv\Scripts\python.exe -c "from backend.dynamic_simulation import run_dynamic_comparison; r=run_dynamic_comparison({'seed':2026,'nodes':32,'gpus_per_node':8}); print({k:v['metrics'] for k,v in r['policies'].items()})"
```

The model formulae, inputs, assumptions, policy definition, and known integration gaps are documented in [`notes/model-specification.md`](../notes/model-specification.md).
