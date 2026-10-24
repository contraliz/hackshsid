# Operational simulation batches

`tools/operational_experiments.py` runs reproducible scenario batches against the repository's existing `backend.dynamic_simulation.run_dynamic_comparison` implementation. Each scenario/seed is one simulator call; its unscheduled baseline and always-on, reactive, and forecast results therefore share that call's exact request trace, flexible-workload inputs, renewable profile, tariff assumptions, and accounting.

The CLI runs Python in-process. Use the project environment so the simulator's SciPy/HiGHS dependencies are available:

```powershell
D:\programming\hackshsid\.venv\Scripts\python.exe tools\operational_experiments.py --seeds 2026 2027 --output-dir results\operational-experiments\two-seeds
```

The default run uses seed `2026`, all three scenarios, and creates a timestamped directory below `results/operational-experiments/`. A focused run can select scenarios and tune the simulator's supported forecast controls:

```powershell
D:\programming\hackshsid\.venv\Scripts\python.exe tools\operational_experiments.py `
  --seeds 11 --scenarios normal_day demand_burst constrained_fleet `
  --forecast-alpha 0.3 --margin-fraction 0.15 --min-active-fraction 0.25 `
  --output-dir results\operational-experiments\seed-11
```

Outputs are `summary.csv` (one baseline row plus one row per seed/scenario/controller) and a readable `report.md`. Failed simulator calls are written as failed rows for all three controllers and cause a nonzero exit code after the outputs are saved. Missing or null metrics are blank in CSV and displayed as `—` in Markdown; they are never replaced with zero.

The repository includes a real one-seed sample at `results/operational-experiments/seed-2026/`. It contains one unscheduled baseline plus three scheduled-controller rows per scenario (12 rows total). The report records whether the backend supplied the canonical baseline/comparison fields; older API responses receive an explicit compatibility warning instead of treating scheduled `always_on` as the naive baseline.

For that seed-2026 normal-day run, the selected Forecast controller's canonical comparison reports facility electricity from 3,074.657 to 2,882.959 kWh (6.24% lower), grid imports from 2,562.657 to 2,370.959 kWh (7.48% lower), cost from 1,504.581 to 1,373.519 CNY (8.71% lower), and operational emissions from 1,409.462 to 1,304.028 kg CO₂ (7.48% lower). Both approaches completed 2,037 requests, with 7 running at the horizon, no queued or rejected requests, and all 6 flexible deadlines met. Latency differed: mean wait was 5.57 vs 0 minutes, P95 wait 39 vs 0 minutes, and mean completion latency 12.67 vs 7.10 minutes. These are synthetic results under the recorded example tariff and carbon assumptions.

## Included scenarios

| Scenario | Inputs |
|---|---|
| `normal_day` | The simulator's seeded one-day request generator with its optional hidden burst disabled; 32 nodes × 8 GPUs. |
| `demand_burst` | The same seeded normal trace plus 80 interactive requests arriving together at minute 720, each requesting 4 GPUs for 2 minutes. The injected peak is 320 offered GPUs against the 256-GPU fleet. This is an explicit synthetic stress case, not an observed event. |
| `constrained_fleet` | A controlled trace of 16 simultaneous 8-GPU batch requests against 2 nodes × 4 GPUs (8 GPUs total). Its workload may exceed the horizon capacity, and the fixed flexible-job LP may report infeasible admission. |

The simulator API currently has no renewable-profile override. Every scenario uses its fixed synthetic 24-hour renewable profile. The CLI does not add a renewable-shortfall flag or claim to have generated a different supply profile.

## Interpretation and limits

CSV metrics are taken from the simulator's unscheduled baseline, per-controller `metrics`, `comparisons`, `replay`, and `assumptions` response fields. Every successful new-schema run emits an `unscheduled_baseline` row and three `scheduled_policy` rows. Each scheduled row includes absolute unscheduled baseline values in `unscheduled_baseline_*` columns and the canonical comparison's savings and service-equivalence fields. `state_*_node_minutes` counts observed replay frame node states; `state_transition_count` counts adjacent-frame node state changes. The metric names preserve the simulator's reported units (including facility/grid kWh, renewable kWh, CNY, kg CO₂, GPU-hours, GPU-minutes, and interval counts).

The headline comparison is the simulator's canonical scheduled-versus-unscheduled result. The baseline is all-nodes-active, immediate FIFO/ASAP request and flexible work without energy scheduling. The existing `always_on` controller remains a distinct diagnostic because it uses the flexible-job LP. Electricity percentage means facility kWh; grid import is reported separately. The API provides `(baseline − scheduled) / baseline × 100`; negative values mean increases. The CLI does not recompute or relabel these values. It shows savings percentages only when `service_comparable` is true, retains any backend-reported raw percentages in `*_pct_reported` CSV columns when service differs, and shows the service note beside the result. Null percentages remain unavailable; the API supplies denominator/unavailable reasons in `*_savings_reason` columns.

Service performance is shown beside energy and cost: completed, queued, running, and rejected requests; mean/P95 queue wait; mean completion latency; flexible admission, GPU-hours delivered/unmet, and deadlines. Equal terminal service outcomes do not imply equal latency. The separate `cost_change_cny_vs_always_on` / `cost_savings_pct_vs_always_on` fields preserve the older scheduled-controller diagnostic and are gated on matching request terminal statuses and flexible-work outcomes. Infeasible flexible admission and its simulator reason appear in the report/CSV.

The report includes the simulator's source/status text for traffic, node power/PUE, tariff, and grid-carbon assumptions. The tariff is a dated Fujian agent-purchase proxy/example, not a verified Xiamen customer rate. The 0.55 kg CO₂/kWh grid factor is an East-China annual average, not marginal hourly carbon or lifecycle CO₂e. Power, workload, and energy data are synthetic illustrative assumptions; outputs are not site measurements, savings guarantees, or operating instructions.

The runner imports the in-repository simulator directly and does not add dependencies, reimplement its controller, change backend inputs, or make an HTTP request. For API-level tests, run the server and post the same scenario payload to `/api/dynamic-simulation`; the backend route returns the three policy results in the same comparison shape.
