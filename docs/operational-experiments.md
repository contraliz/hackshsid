# Operational simulation batches

`tools/operational_experiments.py` runs reproducible scenario batches against the repository's existing `backend.dynamic_simulation.run_dynamic_comparison` implementation. Each scenario/seed is one simulator call; its always-on, reactive, and forecast results therefore share that call's exact request trace, flexible schedule, renewable profile, tariff assumptions, and accounting.

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

Outputs are `summary.csv` (one row per seed/scenario/controller) and a readable `report.md`. Failed simulator calls are written as failed rows for all three controllers and cause a nonzero exit code after the outputs are saved. Missing or null metrics are blank in CSV and displayed as `—` in Markdown; they are never replaced with zero.

The repository includes a real one-seed sample at `results/operational-experiments/seed-2026/`. It ran all three scenarios through the current simulator and produced nine successful controller rows.

## Included scenarios

| Scenario | Inputs |
|---|---|
| `normal_day` | The simulator's seeded one-day request generator with its optional hidden burst disabled; 32 nodes × 8 GPUs. |
| `demand_burst` | The same seeded normal trace plus 80 interactive requests arriving together at minute 720, each requesting 4 GPUs for 2 minutes. The injected peak is 320 offered GPUs against the 256-GPU fleet. This is an explicit synthetic stress case, not an observed event. |
| `constrained_fleet` | A controlled trace of 16 simultaneous 8-GPU batch requests against 2 nodes × 4 GPUs (8 GPUs total). Its workload may exceed the horizon capacity, and the fixed flexible-job LP may report infeasible admission. |

The simulator API currently has no renewable-profile override. Every scenario uses its fixed synthetic 24-hour renewable profile. The CLI does not add a renewable-shortfall flag or claim to have generated a different supply profile.

## Interpretation and limits

CSV metrics are taken from each controller's simulator `metrics`, `flexible_schedule`, `replay`, and `assumptions` response fields. `state_*_node_minutes` counts observed replay frame node states; `state_transition_count` counts adjacent-frame node state changes. The metric names preserve the simulator's reported units (including facility/grid kWh, renewable kWh, CNY, kg CO₂, GPU-hours, GPU-minutes, and interval counts).

`cost_change_cny_vs_always_on` is always-on cost minus the selected controller's cost. `cost_savings_pct_vs_always_on` is emitted only when request IDs have identical terminal statuses and flexible jobs have identical admission, deadline, and delivered/unmet outcomes. Latency remains reported independently, so equal horizon service outcomes do not imply equal response quality. The percentage is left blank when always-on cost is zero. Infeasible flexible admission and its simulator reason appear in the report/CSV. Incomplete service is not presented as savings against a fully served baseline.

The report includes the simulator's source/status text for traffic, node power/PUE, tariff, and grid-carbon assumptions. The tariff is a dated Fujian agent-purchase proxy/example, not a verified Xiamen customer rate. The 0.55 kg CO₂/kWh grid factor is an East-China annual average, not marginal hourly carbon or lifecycle CO₂e. Power, workload, and energy data are synthetic illustrative assumptions; outputs are not site measurements, savings guarantees, or operating instructions.

The runner imports the in-repository simulator directly and does not add dependencies, reimplement its controller, change backend inputs, or make an HTTP request. For API-level tests, run the server and post the same scenario payload to `/api/dynamic-simulation`; the backend route returns the three policy results in the same comparison shape.
