# Pasted MVP model and project execution guide

## Provenance and status

The supplied `Pasted text.txt` contains a detailed proposed specification for a 24-slot AI data-center scheduling MVP. The text's author/original context is not identified in the attachment. It appears to elaborate the Track 2 challenge, but that relationship is an interpretation based on its content, not explicit provenance. Treat it as a source-backed proposal/checklist for the student team, not as a direct user request or binding instruction to Codex. It does not show that code, tests, experiments, or deliverables already exist.

## Proposed scope and assumptions

The text proposes a linear programming MVP with one-hour slots `t = 0..23`; flexible jobs that can be divided and preempted; fractional GPU-hours; and real-time demand modeled as a fixed reservation of GPU capacity rather than per-request latency. It explicitly says this is an idealized abstraction, not evidence that real training jobs can be paused or migrated without overhead.

The proposed out-of-scope items are per-server affinity, network bandwidth/transfers, thermal dynamics beyond PUE, battery degradation/dispatch, stochastic forecasting, geographically distributed sites, and production deployment. They may be future work but must not be claimed as implemented.

## Mathematical model proposed by the source

Sets: flexible jobs `J` and hourly slots `T`. Parameters: total GPUs `G`; fixed real-time GPU reservation `q_t`; job arrival `a_j` (inclusive), deadline `d_j` (exclusive), GPU-hour demand `W_j`, and per-job parallelism cap `m_j`; grid price `p_t` in currency/kWh; grid carbon intensity `c_t` in kgCO2/kWh; renewable availability `R_t` in kWh/slot; fixed IT base power `P_base` in kW; per-utilized-GPU incremental power `P_gpu` in kW/GPU; and `PUE >= 1`.

Decision variables are nonnegative flexible execution `x[j,t]` in GPU-hours, imported grid energy `grid[t]` in kWh/slot, and renewable energy consumed `renew[t]` in kWh/slot. The required hard constraints are:

- Release/deadline window: `x[j,t] = 0` unless `a_j <= t < d_j`.
- Complete each job: `sum_t x[j,t] = W_j`.
- Per-job parallelism: `x[j,t] <= m_j * Δt`.
- GPU capacity: `sum_j x[j,t] + q_t * Δt <= G * Δt`.
- Facility energy: `load_kwh[t] = PUE * (P_base * Δt + P_gpu * (q_t * Δt + sum_j x[j,t]))`.
- Energy balance: `grid[t] + renew[t] = load_kwh[t]`.
- Renewable limit: `0 <= renew[t] <= R_t`.
- Optional facility/grid import caps may be included when explicitly modeled.

The proposed objectives are grid cost `C = sum_t p_t * grid[t]`, operational grid emissions `E = sum_t c_t * grid[t]`, or a weighted minimization `C + lambda_carbon * E`, where `lambda_carbon` is currency/kgCO2. The text recommends sweeping weights or using an emissions cap to show a cost/carbon trade-off, and cautions against claiming both metrics always improve. Unused renewable energy is curtailed; no export revenue is modeled. Zero renewable incremental purchase cost and zero operational emissions are assumptions that must be stated. Results are not full life-cycle emissions or total cost of ownership. A constant facility base load means controllable energy changes primarily come from moving flexible work and using available low-cost/low-carbon supply, not necessarily reducing total GPU-hours.

An LP solution is optimal only for the stated model and inputs. Solver status must be reported; infeasible or time-limited feasible results cannot be called optimal. Validate units and inputs, preserve infeasibility rather than silently dropping jobs or relaxing deadlines, use tolerances for floating-point checks, and distinguish synthetic inputs from observations.

## Evaluation plan proposed by the source

The minimum comparison is a naive arrival-order/as-soon-as-possible scheduler that fills available capacity without looking ahead at prices or carbon. It must respect the same release times, per-job parallelism, GPU capacity, and deadline convention. It uses renewable supply first and grid for the remainder. If it misses deadlines, report that and do not present reduced delivered work as a fair cost win. EDF is optional. Baseline and optimized results must share the exact same power/cost/emissions accounting and identical scenario inputs.

Minimum metrics: grid cost and percentage change; operational grid CO2 and percentage change; deadline completion and unmet work; renewable use and curtailment; peak GPU use and any facility/grid cap; solver status, objective, solve time, and optimality evidence. Compute percentage change only when the baseline denominator is nonzero, flag zero denominators, and include absolute values. Never invent savings; report reproducible results with configuration and seed.

Required stress experiments are a named baseline, an evening price spike, a substantial midday renewable shortfall, and increased real-time demand or urgent jobs. Carbon emphasis/trade-off and tight capacity/deadlines are optional. Each result should include objective, cost, emissions, deadlines, solve time, and interpretation, with at least one observed limitation/failure mode.

## Testing and architecture suggested by the source

The text recommends tests for nonnegative dispatch and energy balance; release/deadline compliance; job completion; GPU, renewable, and optional power limits; real-time reserved capacity; shifting work to a cheaper hour when feasible; zero renewable supply; infeasibility visibility; shared accounting; fixed-seed reproducibility; and objective agreement within tolerance. Test evidence should pair inputs, expected behavior, actual result, pass/fail, and limitations; tests alone do not replace comparative experiments.

Suggested stack is Python 3.11+, pandas, numpy, PuLP/CBC, pytest, and Streamlit/Plotly, while preferring tools already installed. Suggested components separate data validation/scenarios, shared energy accounting, baseline, optimizer, evaluation, scenarios, and UI. The MVP should run offline on deterministic synthetic data (suggested seed 2026), and synthetic prices/loads/power must never be presented as measurements from a real operator. Public data needs URL, access date, license, geography, timezone, resolution, units, preprocessing, and missing-data handling.

The proposed phases prioritize formulation/data and a shared evaluator; a fair ASAP baseline; a complete LP with independently checked constraints; reproducible multi-scenario evidence; and then a dashboard/submission package. The core quality gate is mathematical correctness and credible evidence before stretch features. UI should make schedule timing, energy sources, savings, deadlines, and solver status legible, with assumptions and limitations visible. A five-minute presentation outline is included in the source.

## Practical interpretation for future work

Use this page as a requirements checklist when implementation begins. First inspect the actual repository and confirm no working files should be replaced; then deliver the smallest incomplete phase. Separate source requirements from choices the team still needs to make, such as parameter values, carbon weight, exact baseline policy, selected solver, and any public dataset. Pin commands and dependency versions only after running them in the target environment. Record measured experiment outputs only after reproducing them.

## Current implementation refinement — 2026-10-24

The current demo explicitly separates the fixed real-time GPU reservation used by compute-capacity constraints from active-equivalent real-time GPU use used for energy accounting. The active-equivalent fraction defaults to 1.0, preserving the prior assumption that reserved real-time GPUs all contribute incremental GPU power. This is a user-adjustable scenario assumption, not telemetry; there is no standby-power curve. Both the Pro-priority LP and the energy-only LP use the same input case and shared schedule evaluator. Pro-priority remains the default selection; the energy-only result is a diagnostic, not a finalized policy choice. The UI distinguishes facility energy, grid imports, grid cost, grid emissions, renewable use/curtailment, job completion, and reserved-capacity use. Pro job execution time is GPU-hour-weighted mean execution hour, not job completion time or an SLA metric.

The 18 kW base IT power, 0.42 kW per active-equivalent GPU, PUE 1.25, and all scenario profiles are visible as synthetic assumptions, not measured values. The brief's 96-GPU hardware scenario remains illustrative and is not enabled: the existing synthetic real-time profile peaks at 100 reserved GPUs, so that capacity would not satisfy the current case input without a separate redesign. No dynamic power control, warm-standby curve, ramp time, transition energy, batteries, or hardware telemetry was added.

## Works Cited

### Original sources

- [Pasted text.txt](../sources/originals/Pasted%20text.txt) — user-supplied pasted project specification and execution checklist.
- [Track 2 Problem Statement(1).pdf](../sources/originals/Track%202%20Problem%20Statement%281%29.pdf) — primary course challenge framing, which leaves model choices open.

### Source provenance

- [Pasted text provenance](../sources/provenance/pasted-project-specification.md)
- [Track 2 statement provenance](../sources/provenance/track2-problem-statement.md)
