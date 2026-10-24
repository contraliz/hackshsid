# GridShift — HackSHSID Track 2 prototype

GridShift is a local, interactive demonstration of AI data-center compute and electricity co-scheduling. By default, it runs a linear program with Pro flexible-work earliness priorities and compares it with a Pro-priority ASAP baseline. An energy-only LP can be selected as a same-input diagnostic; both LP policies are evaluated for every run. The app also includes a deterministic non-preemptive Pro-first real-time request queue.

All included workload, prices, grid-carbon values, renewable supply, and power coefficients are deterministic synthetic assumptions (seed 2026). They are not measurements from a data center. This is a school-project prototype, not an operations control system.

## Run locally

Requirements: Python 3.11 or newer, Node.js 20.19 or newer, and npm. The Python and JavaScript dependencies are local; the demo does not call a paid provider or external data API.

### Development mode

From the project root, open two PowerShell terminals.

Terminal 1 — install Python dependencies and start the optimizer API:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

Terminal 2 — install frontend dependencies and start the interface:

```powershell
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite sends `/api` requests to the local Flask service at `http://127.0.0.1:8000`.

### Built local preview

```powershell
npm install
npm run build
.\.venv\Scripts\python.exe server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The Flask process serves both the API and the built frontend. The API health endpoint is `/api/health`.

## Windows executable

The portable Windows x64 build bundles the Python runtime, Flask, SciPy/HiGHS, and the built frontend. The recipient does not need Python or Node.js. Extract the entire `GridShift-Windows-x64.zip` folder and double-click `GridShift.exe`; a small status window provides **Open GridShift**, **Copy address**, and **Stop and exit** controls. The app chooses an unused port and binds only to `127.0.0.1`. The build is unsigned and Windows SmartScreen may warn.

Build it on Windows from the project root with `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1`. The script runs `npm ci` if frontend dependencies are absent, builds the frontend, installs the pinned packaging tool, and creates `releases/GridShift-Windows-x64/GridShift.exe` plus `releases/GridShift-Windows-x64.zip`. See [packaging/README-Portable.txt](packaging/README-Portable.txt) for recipient instructions.

## Demo guide

1. Start on **Balanced day** and compare the Pro-priority ASAP baseline with the selected LP schedule.
2. Use **Optimizer policy** to choose Pro-priority (the default) or energy-only. Both are solved on the same inputs and shown in a diagnostic. Use the **Flexible jobs** table to change which synthetic jobs are Pro. The Pro-priority LP minimizes each Pro job's GPU-hour-weighted execution-time objective in stable release/row order before the energy objective.
3. In **Real-time request priority queue**, select an hour, edit or add Pro/Standard requests, and run the simulation. Use **Step next** or the timeline slider to inspect arrival, start, completion, waiting order, and reserved GPU usage. **Replay** returns to the first event; **Reset sample** restores the demonstration requests.
4. Open **Scenario adjustments** to change renewable supply, flexible-work demand, or the active-equivalent real-time GPU assumption; edit **Total GPUs** or **Carbon weight** as well. Active-equivalent use affects energy accounting only. Capacity remains reserved against the full real-time GPU count. The default ratio of 1.0 preserves the prior assumption that all reserved GPUs are active; this control is not telemetry.
5. Choose **Evening price spike** or **Renewables shortage**, then press **Run schedule**. The charts and metrics are recalculated from those inputs.
6. Increase the workload with **Demand surge**. If there is no feasible schedule, the app shows the solver's infeasible status and the ASAP baseline's delivered and unmet work. It hides optimized metrics and savings claims.
7. Open **Model assumptions** to review simplifications. The flexible-job table shows tier, release/deadline, work delivered, and GPU-hour-weighted average execution time (not job completion time).

The displayed synthetic cost unit is **CU** per kWh. The carbon weight is measured in CU per kgCO₂e. Cost and emissions changes use `(ASAP − optimized) / ASAP`; a negative result means the optimized method increased that quantity. Percentage changes are shown only when both methods complete all work and the baseline denominator is nonzero.

## Model

The horizon has 24 one-hour slots, `t = 0..23`. For each flexible job `j`, the optimizer chooses `x[j,t] >= 0` GPU-hours, imported grid energy `grid[t] >= 0` kWh, and renewable energy `renew[t] >= 0` kWh. The solver is SciPy `linprog` with its HiGHS backend.

For each job, work is completed inside its release/deadline window, where arrival is inclusive and deadline is exclusive. Hourly job execution is bounded by its parallel-GPU limit. Total flexible use plus the fixed real-time GPU reservation must not exceed installed GPU capacity.

Hourly capacity uses the full reserved real-time GPU count. For energy accounting, hourly facility electricity is:

```text
load_kwh[t] = PUE × (base_IT_kW × 1 hour
                   + GPU_kW_per_GPU × (active_equivalent_real_time_GPUs[t]
                                        + flexible_GPU_hours[t]))
grid[t] + renew[t] = load_kwh[t]
0 <= renew[t] <= renewable_available_kwh[t]
```

Grid cost is `C = sum(price[t] × grid[t])`; operational emissions are `E = sum(grid_carbon_kg_per_kwh[t] × grid[t])`. For each Pro job in stable `(arrival, input row)` order, a separate LP pass first minimizes its earliness score `sum(t × x[j,t])`, in GPU-hour-hours. Each attained optimum is retained by two linear constraints within `max(1e-7, 1e-8 × |optimum|)` before the next pass. A final LP pass minimizes `C + carbon_weight × E`. If no Pro jobs are selected, the model is the prior energy-only LP. All job completion, release/deadline, per-job parallelism, and GPU capacity constraints remain hard throughout every pass. This is a priority commitment inside the model, not a blanket promise that every Pro GPU-hour precedes every Standard GPU-hour; Standard may need early hours to satisfy a tighter hard deadline. LP optimality is for the stated lexicographic policy, this model, and these supplied inputs.

The **Priority ASAP** baseline schedules Pro jobs first, then Standard jobs; within each tier it follows arrival and input order and fills the first available capacity without looking ahead at prices or carbon intensity. It and both LP policies use the same case and energy/cost/emissions evaluator. The Pro-priority LP minimizes each Pro job's GPU-hour-weighted execution time (`sum(hour × GPU-hours) / delivered GPU-hours`) in stable release/row order before the energy objective. This is a work-weighted average execution time, not job completion time. The energy-only LP drops those earliness stages while retaining hard job completion, capacity, and deadline constraints. The UI reports both LP outcomes as a diagnostic and leaves policy choice to the user. If ASAP misses a deadline, the app reports that result and hides percent comparisons because delivered work is not apples-to-apples. Pro earliness may increase modeled cost or emissions versus energy-only; the UI uses shared-accounting values and does not assume both always improve.

The **real-time request queue** applies the same simulated Pro-before-Standard preference to individual arriving requests. Requests run without preemption. The queue uses the selected hour's reserved real-time capacity and does not count those simulated requests again in daily energy. It uses bounded backfill: an earlier request that does not fit the free GPUs may be skipped for the next fitting request in its tier; a Standard request can start only when no queued Pro request fits. Pro requests can therefore delay Standard requests indefinitely under continuous arrivals. This is a local queue demonstration, not live serving or a measured latency/SLA result.

## Scenarios and controls

- **Balanced day:** a synthetic hourly price, carbon-intensity, renewable, and real-time-demand profile.
- **Evening price spike:** the same profile with higher evening grid prices.
- **Renewables shortage:** the same profile with lower midday renewable availability.
- **Demand surge:** higher fixed real-time reservations and 1.8× flexible demand by default; this stress case is intentionally likely to be infeasible at default capacity.
- **Total GPUs:** shared compute limit, 100–512. Inputs below the case's real-time reserve are rejected clearly.
- **Carbon weight:** 0–0.8 CU/kgCO₂e.
- **Renewable supply:** 0–1.5× synthetic availability.
- **Flexible-work scale:** 0.5–2.5× each job's GPU-hour demand.

The default power assumptions are 18 kW fixed IT base power, 0.42 kW per active-equivalent GPU, and PUE 1.25. The active-equivalent real-time GPU fraction defaults to 1.0 times the reserved count; changing it changes modeled power but never releases reserved compute capacity. No standby curve or active-use telemetry is modeled. The brief's optional 96-GPU hardware reference remains illustrative and is not offered as a scenario: the current synthetic real-time profile peaks at 100 GPUs, so switching to 96 would require a separately reviewed input redesign. None of these coefficients or hardware references are measured operating data.

The comparison table reports grid cost, operational grid emissions, facility energy, grid imports, weighted objective, deadline completion, unmet work, renewable use/curtailment, peak reserved-capacity GPU use, peak active-equivalent power use, solver status, and solve time. A separate diagnostic compares Pro-priority LP with energy-only LP on the same input. The hourly energy chart compares ASAP and selected-LP renewable use/grid imports side by side.

## Real-time Pro priority queue

`POST /api/realtime-queue` replays up to 32 synthetic request records against the fixed real-time GPU reservation for one selected scenario hour. A record supplies a simulated subscriber tier, arrival minute (0–119), GPU count (1–512), and duration (1–120 minutes). At each event time, the simulator releases completed work, enqueues arrivals, and fills available capacity. It starts the earliest-arrived eligible Pro request before any eligible Standard request; it never interrupts a request that is already running. FIFO within a tier is arrival minute then input order. If the next request is too large for currently free GPUs, bounded backfill can start a later fitting request in that tier; Standard may backfill only when no queued Pro request fits. A request larger than the selected hour's full reservation is explicitly rejected.

Queue timing and states are deterministic from their inputs and have no shared server-side state. The request simulator uses the selected hour's **existing fixed real-time reservation**. Requests are not added again to hourly facility energy or flexible-job load. Pro/Standard are simulated subscriber labels; GridShift has no user accounts, actual subscription enforcement, billing, or inference runtime. Long-running or continuous Pro arrivals can delay Standard work; no latency/SLA result is measured.

## Dynamic node-state simulation

The **Node power-state simulation** panel is an additional minute-resolution comparison. It sends one generated request trace (seed shown in the result) through three strategies: all nodes active, reactive scale-up from current queued/running demand, and a causal EWMA forecast that maintains a warm-node target. Default inventory is a synthetic 32 × 8 = 256 GPUs; the **Illustrative 96-GPU reference** button selects 12 × 8 without changing the old hourly model's defaults. Nodes move among active, warm, booting, and off states; warm-to-active is 5 minutes and off-to-warm is 20 minutes in this illustration. The inputs expose EWMA alpha, fallback forecast margin, and a 25% default active-capacity floor. State snapshots report offered demand, forecast, target warm count, and node states.

All strategies receive the same seeded synthetic Poisson request trace and use the same queue and energy accounting. Interactive requests dispatch first; batch requests waiting at least 15 minutes are promoted. Requests do not preempt running work. Fleet-exceeding requests and arrivals beyond the 256-request queue bound are reported as rejected. The reported class latency allowances (interactive 2 minutes, batch 30 minutes) are synthetic diagnostics, not SLAs. Cost uses an October 2026 Fujian State Grid agent-purchase tariff example as a CNY proxy, not a verified Xiamen customer tariff. Grid emissions use the official East-China annual-average 2023 factor; hourly renewable availability comes from the old synthetic hourly profile. All node, GPU, PUE, and traffic values are unmeasured scenario assumptions.

The new minute simulator currently covers request traffic only. Flexible training/batch jobs remain in the separate existing 24-hour LP and are not claimed completed in the node-state comparison. Deadline-safe coordination between dynamic node states and flexible LP allocations, historical forecast-error calibration, site-specific measured power, and an account-specific Xiamen tariff remain open implementation/data gaps. The full finalized policy, equations, assumptions, official tariff evidence, and acceptance criteria are in [the dynamic co-scheduling model specification](notes/model-specification.md). Reproduction and actual synthetic outputs are in [the seed-2026 dynamic simulation receipt](results/dynamic-simulation-seed-2026.md).

## Assumptions and limits

- Flexible jobs are divisible and preemptible, and fractional GPU-hours are allowed. This does not establish that real training jobs can pause or migrate without overhead.
- Real-time work is represented as an exogenous reserved GPU count, not per-request latency or service-level modeling.
- The real-time queue is a request-state simulation, not real inference. Pro priority can delay queued Standard requests under continuous Pro arrivals. Already-running work is not preempted; fitting-request backfill may skip a larger queued request.
- Pro/Standard are manually selected synthetic metadata, not authenticated or billed subscription tiers. The lexicographic LP protects Pro earliness preferences but never relaxes Standard completion deadlines.
- Renewable generation has no incremental purchase cost in the demo, unused renewable supply is curtailed, and exports earn no revenue.
- Emissions count grid operational CO₂e only. This is not a life-cycle assessment or total cost-of-ownership model.
- Inputs are deterministic and synthetic. No forecast error or uncertainty is modeled.
- Server affinity, network transfers/bandwidth, cooling dynamics beyond PUE, batteries, geographic distribution, and production deployment are out of scope.
- The prototype has no authentication, data persistence, or deployment controls. Do not connect it to a real data center.

## Checks and reproducible scenarios

Run the model and API tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Reproduce the baseline, price-spike, renewable-shortage, demand-surge, and carbon-weight comparison outputs:

```powershell
.\.venv\Scripts\python.exe scripts/run_experiments.py
```

The script writes `results/scenario_comparison.csv` and `results/scenario_comparison.md`. Test coverage and observed sample outputs are summarized in `results/testing-evidence.md`.

## Project notes

- [Course and event requirements](notes/course-assessment-requirements.md)
- [Track 2 problem and evaluation questions](notes/track2-problem-and-evaluation.md)
- [Source-derived MVP specification](notes/mvp-model-and-execution-guide.md)
- [Source archive, provenance, and reading limitations](sources/coverage.md)
- [Design system and concept fidelity notes](design/spec.md)
- [Generated desktop concept](design/concepts/gridshift-desktop.png), [mobile concept](design/concepts/gridshift-mobile.png), and [infeasible-state concept](design/concepts/gridshift-infeasible.png)
- [Visual QA comparison and browser screenshots](design/visual-qa.md)
