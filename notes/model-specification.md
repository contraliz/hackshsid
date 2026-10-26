# GridShift Dynamic Co-Scheduling Model

**Status (2026-10-26):** DEC-0008 and Sections 11–12 describe the current minute simulator. Sections 1–10 preserve the earlier DEC-0006/DEC-0007 policy and are historical wherever they conflict with DEC-0008. Current behavior and source-grounded explanation are in [simulation-explained.md](../docs/simulation-explained.md). Numerical settings remain agent-selected, configurable illustrations—not separately user-approved measurements, service guarantees, or measured savings. No real infrastructure should be controlled from this classroom model.

**Current prototype:** `backend/data.py` still supplies hourly synthetic prices, renewables, and `REALTIME_GPUS`; `backend/scheduler.py` still runs its hourly LP and shared evaluator; `backend/priority_queue.py` still replays user-supplied requests against that fixed reservation. These inputs are not a request history or warm-node telemetry. The operational simulator described here is additive; it does not reinterpret the fixed reservation as warm capacity or silently change the existing hourly API/defaults. See [README](../README.md) and [MVP model guide](mvp-model-and-execution-guide.md).

**Historical v0 snapshot (superseded):** The original 2026-10-24 implementation used a five-minute warm activation, a 25-minute cold-to-active total, a scalar reserve formula and flexible-work commitments that could block request starts. Those choices are retained below as design history only. The current simulator still exposes `POST /api/dynamic-simulation`, uses the same 32×8 default fleet and traffic generation, and maintains the same energy model; its current arrival, readiness, flexible dispatch and standby behavior is specified in Section 11–12 and in the linked simulation guide.

The minute simulator's IT power is `18 kW fixed overhead + 1.0 kW × active nodes + 0.25 kW × warm nodes + 1.2 kW × booting nodes + 0.35 kW × (running request GPUs + running flexible GPUs)`, multiplied once by PUE 1.25. These are synthetic placeholders. It uses the existing synthetic hourly renewable profile, the dated Fujian tariff example below as a CNY proxy, and the cited East-China annual-average CO₂ factor. Its metrics and assumptions appear in the API response and UI. The dynamic comparison now obtains one fixed Pro-priority hourly LP schedule and shares it across always-on, reactive, and forecast controllers. LP capacity admission retains the existing reserved-realtime curve as a capacity reservation; generated request work replaces that placeholder in minute-level power accounting, so reservation is not counted as extra GPU activity. The minute controller starts capacity ahead of known accepted commitments, commits flexible GPU-minutes before dispatching requests, and declines any request that would consume capacity required by its scheduled work over the request's non-preemptive duration. LP-infeasible jobs are labeled not admitted; runtime commitment shortfall and per-job deadline misses are reported. The API accepts optional validated `request_trace` and `flexible_jobs` arrays for controlled scenarios; absent overrides, it uses the seeded default trace and existing LP job set. No runtime flexible reallocation or preemption is implemented. Historical forecast-error calibration, node-specific measured power curves, and tariff selection for a known Xiamen customer remain data/model gaps. These are not assumed features.

The minute replay additionally carries the forecast controller's reserve decision and current node readiness on every frame. The node view shows the uncapped target separately from warm-ready, booting and warming nodes, plus active spare, the pre-5-minute active-capacity gap, bridge-window readiness gap, and installed-fleet gap. These values describe the synthetic forecast and readiness model; they are not telemetry or an SLA.

## 1. Units, state, and configurable defaults

Use one homogeneous pool within a scenario. Allocate at GPU granularity; model power-state actions at node granularity unless a selected, documented platform supports independent GPU power gating. Inventory is fixed during a run.

| Symbol / parameter | Unit | Illustrative default | Provenance / interpretation |
|---|---:|---:|---|
| (N), nodes | nodes | 32 | Current minute-simulator default; configurable fixture, not the installed user's fleet. A separate 12 × 8 = 96-GPU reference preset is illustrative only. |
| (g), GPUs per node | GPUs/node | 8 | Synthetic homogeneous-node assumption; replace with selected inventory. |
| (G_{fleet}=Ng) | GPUs | 256 | Fixed capacity per run at the default; changing node state never changes inventory. |
| (Delta_s), event step | minutes | 1 | Resolves request arrivals, durations, and power transitions. Results are quantized to one minute. |
| (Delta_f), forecast bucket | minutes | 5 | Arrival-rate EWMA bucket. |
| (Delta_{LP}), flexible plan bucket | hours | 1 | Retains the current 24-slot LP horizon; the controller rolls it forward. |
| tau_W, warm-to-active | minutes | 5 | Placeholder only; sensitivity 1–15 min. A warm node is powered in low-power standby, not yet dispatch-ready. |
| tau_B, cold-boot-to-warm | minutes | 20 | Placeholder only; sensitivity 10–60 min. Booting nodes do not count as active or warm. |
| tau_C, powered-off-to-active total | minutes | 25 (=20+5) | `tau_B + tau_W`; a cold node is not active capacity until boot and warm activation both finish. |
| (P_{A0}), active node idle IT power | kW/node | 1.0 | Normalized placeholder for an 8-GPU synthetic node; sensitivity 0.5–1.5. It includes host and idle-GPU draw. |
| (P_W), warm node IT power | kW/node | 0.25 | Unmeasured placeholder (25% of (P_{A0})); sensitivity 15–50%. No hardware capability is asserted. |
| (P_B), cold boot average IT power | kW/node | 1.2 | Unmeasured placeholder during boot; sensitivity 0.8–1.5 × (P_{A0}). Prefer a measured transition trace. |
| (P_{Delta GPU}), active compute increment | kW/occupied GPU | 0.35 | Unmeasured illustrative power above active-idle baseline; sensitivity 0.2–0.5. Do not add it if using full measured node power at each utilization. |
| (P_{site}), fixed IT overhead | kW | 18 | Carries forward the existing synthetic `base_it_kw`; not a site measurement. Must exclude node power already counted. |
| PUE | dimensionless | 1.25 | Existing synthetic assumption, not measured; sensitivity 1.15–1.6. |
| (alpha), EWMA coefficient | dimensionless | 0.30 | Proposed; sensitivity 0.15–0.50, chosen by rolling-origin validation. |
| Forecast error history | completed startup windows | 28 | Current implementation threshold; errors mature causally inside a run and are synthetic/overlapping, not 28 independent days. Until then use manual fallback. |
| Forecast upper quantile | probability | 95% | Proposed reserve-risk setting, not an SLA. Sensitivity 90%, 95%, 99%. |
| Manual fallback margin floor | GPUs | 4 | Configurable scenario assumption; used until enough prior forecast windows mature. |
| Manual fallback margin fraction | fraction | 0.15 | Configurable scenario assumption; `M=max(floor, fraction × predicted bridge peak)`, not calibrated. Sensitivity 10–35% plus 0–8 GPU floor. |
| Warm scale-down hysteresis | minutes | 30 continuous below-off condition | Proposed; sensitivity 15–60 min, plus 30-min minimum warm dwell. Never powers down occupied nodes. |
| Flexible checkpoint cost | minutes | 5 min per checkpoint interruption | Proposal only; sensitivity 0–15 min. Count occupied GPU time and energy during checkpointing. |
| Simulated tariff date/category | date + category | 2026-10, 1–10(20) kV agent-purchase example | Official dated provincial example only; not asserted as Xiamen customer's actual contract. Direct-market price remains an explicit scenario input. |
| Grid CO₂ factor | kgCO₂/kWh | 0.5500 | Official 2023 East-China regional annual average, latest located in this research; not hourly marginal CO₂ and not kgCO₂e. |

| Formula variable | Unit | Definition / current meaning |
|---|---:|---|
| `t` | minute | Current simulator decision time. |
| `h` | minutes ahead | Future offset from `t`; the adopted reserve bridge checks integer offsets `tau_w <= h < tau_c`, currently 5 through 24 minutes. |
| `N`, `g` | nodes; GPUs/node | Fixed inventory and homogeneous capacity per node for one scenario. |
| `A_t`, `W_t`, `R_t`, `B_t`, `O_t` | nodes | Current active, warm, warming, booting, and off counts; each node occupies exactly one state. `R_t` is an in-progress warm-to-active transition. |
| `C_t=g A_t` | GPUs | All active capacity, including occupied and spare GPUs. This is a capacity count, not active use. |
| `D_0`, `S_t` | GPUs | Current GPU demand and active spare, `S_t=max(0,C_t-D_0)`. |
| `Delta`, `n_{t,c}` | minutes; requests/bucket | Completed arrival bucket length (5) and observed arrivals of class `c` in that completed bucket. |
| `lambda_{t,c}` | requests/min | Causal EWMA arrival-rate estimate for class `c`, updated from completed buckets only. |
| `r_c` | GPU-minutes/request | Synthetic or explicitly configured workload conversion factor for class `c`. `lambda × r` has units GPUs. |
| `F_t(h)` | GPUs | Accepted flexible GPU allocation from the fixed LP plan at the same future minute `t+h`. |
| `Dhat_t(h)` | GPUs | Predicted total GPU demand at `t+h`: forecast arrivals + known running + averaged known queue pressure + same-minute `F_t(h)`. |
| `M_t(h)` | GPUs | One-sided uncertainty buffer: matured-window quantile when available, otherwise the exposed uncalibrated assumption. |
| `U_t(h)=Dhat_t(h)+M_t(h)` | GPUs | Protected upper-demand estimate at the same future minute. |
| `tau_w`, `tau_B`, `tau_c` | minutes | Warm-to-active (5), cold-boot-to-warm (20), and total off-to-active (`tau_c=tau_B+tau_w=25`). |
| `W_target,t` | nodes | Uncapped integer count from the adopted formula, measuring warm nodes needed beyond currently active capacity. It is a target, not a readiness guarantee. |
| `H_warm` | nodes | Configurable synthetic available-warm overhead, one node by default; distinct from and added after the adopted formula. |
| `W_stock,t` | nodes | Operational warm-stock objective `W_target,t + H_warm`; it is not a capacity guarantee and remains separate from the formula target. |
| `C_ready,t(h)` | GPUs | Capacity projected ready by offset `h`, calculated from current node states and per-node remaining transition ETAs. |
| `G_short,t(h)` | GPUs | Protected demand above installed fleet: `max(0,U_t(h)-N g)`. |

Node state counts are (A_t) active, (W_t) warm, (R_t) warming, (B_t) booting, and (O_t) off, with (A_t+W_t+R_t+B_t+O_t=N). A node is in exactly one state. Active capacity is (C_t=gA_t) GPUs; active use is (D_0) GPUs; existing active spare is (S_t=max(0,C_t-D_0)). Warm nodes do not count as active capacity before their warm-to-active delay. Warming and booting nodes have per-node remaining ETAs and do not count as active until the ETA elapses.

For request (i), record arrival (a_i) (min), requested GPUs (q_i) (GPU), service duration (L_i) (min), class (c_i), start/completion, queue wait (W_i), and completion latency (T_i). For flexible job (j), record release (r_j), deadline (d_j), remaining work (w_j) (GPU-hour), parallel cap (m_j) (GPU), checkpointability, and committed GPU allocations by interval. GPU-hours are work, not a concurrency count: convert to GPU capacity by dividing by interval hours.

## 2. Workload and offered demand

Generate traffic from request arrivals, rather than inferring demand from the capacity-capped served load. The observed/offered stream includes running, queued, rejected, and overflow requests. For a realized trace, offered concurrent demand at minute (t) is the GPU sum of requests whose requested service intervals overlap (t), replayed against an infinite-capacity virtual queue; actual running GPU use and waiting GPU demand are reported separately. This avoids training the forecast on utilization that has already been capped by the fleet.

Proposed deterministic synthetic traffic defaults (all explicitly synthetic; vary them in sensitivity runs):

| Class | Base arrivals | GPUs/request | Duration | Example completion-latency allowance |
|---|---:|---:|---:|---:|
| Interactive inference | 6 requests / 5 min | discrete 1–2 | triangular 2/5/8 min | 2 min |
| Batch inference | 2 requests / 5 min | discrete 2–4 | triangular 5/15/30 min | 30 min |

The tuple notation in this table is minimum/typical/maximum; “typical” is the mode of the triangular draw. The implementation calls Python's triangular sampler with `(low=minimum, high=maximum, mode=typical)` and rounds each continuous draw to integer minutes. Forecast factors use the expected integer duration under those rounding bins, multiplied by the midpoint of the discrete GPU-size range. The resulting factors are 7.5 and 50.0 GPU-minutes/request. This is an analytical synthetic expectation, not a measured class average.

Multiply each class's base arrival rate by a synthetic time-of-day factor: 0.35 from 00:00–06:00; 0.60 from 06:00–09:00; 1.00 from 09:00–17:00; 1.50 from 17:00–22:00; 0.70 from 22:00–24:00. Seeded Poisson arrivals and seeded discrete GPU/duration draws make each trace reproducible. Add seeded 15-minute bursts at 3× the class rate in a configurable fraction of runs (default 25%); future burst events are hidden from the forecaster unless an event calendar is actually known at forecast time. These values do not describe observed Xiamen traffic.

### Representativeness and evidence

This generator is suitable for controlled, same-trace controller comparisons and sensitivity experiments. It is not a realistic empirical model of a production datacenter: class rates, diurnal factors, Poisson independence, burst probability, GPU sizes, and durations are not fitted to a trace. It has no measured temporal autocorrelation, heavy-tailed resource mix, job dependencies, model/token-length effects, per-service behavior, heterogeneous hardware, or per-cluster variation. The [Google Borg 2019 trace study](https://research.google/pubs/borg-the-next-generation/) reports an extremely heavy-tailed resource distribution (top 1% of jobs consume over 99% of resources), changing workload mix, and substantial variation across eight clusters; this two-class bounded-size generator does not represent those properties. The [Alibaba MLaaS trace study](https://www.usenix.org/conference/nsdi22/presentation/weng) analyzes two months from a production cluster with over 6,000 heterogeneous GPUs and reports long queueing delays, low utilization, difficult GPU requirements, and load imbalance. The [Azure public dataset](https://github.com/Azure/AzurePublicDataset) includes LLM inference request traces with input/output tokens collected in November 2023 and May 2024, while this model substitutes coarse fixed-duration classes. Thus Poisson arrivals, class buckets, assumed diurnal rates and a causal EWMA are useful policy inputs, but their realism and forecast accuracy are unvalidated. No published trace is imported or treated as a calibration source.

Flexible ML/batch work keeps the existing job representation: GPU-hour demand, release/deadline window, maximum parallel GPUs, and accepted/committed status. In the new model, defaults are workload fixtures, not calibrated benchmarks. Preserve (w_j) and (d_j) for every accepted job; report an admission rejection before acceptance if its constraints are infeasible. An accepted job is never silently dropped.

## 3. Causal forecast and uncertainty

At a minute decision time `t`, the EWMA is updated every five-minute bucket using only arrivals observed in the **just completed** bucket. For class `c`, `n[t,c]` is its count in the completed bucket, `Delta=5 min`, and `lambda[t,c]` is requests/minute:

\[
\lambda_{t+1,c}=\alpha\frac{n_{t,c}}{\Delta}+(1-\alpha)\lambda_{t,c}.
\]

At the default `alpha=0.30`, the first default-synthetic bucket starts from the configured generator baseline adjusted by its known time-of-day factor and selected synthetic traffic multiplier. The UI presets are Low 0.5×, Normal 1×, and High 2× of generated arrival rates. They scale Poisson frequency only; request class mix, GPU sizes, duration distribution, burst chance, hardware and energy settings remain fixed. Normal is the backwards-compatible default. An explicit `request_trace` is used unchanged and starts its forecast at zero; any traffic preset is reported as not applied. Future traffic uses the known synthetic time-of-day profile; hidden future arrivals and burst draws are never read by the forecast. These generator values and multipliers are scenario assumptions, not observations.

For each request class, `r_c` is GPU-minutes/request. The default value is the product of the synthetic generator's mean requested GPUs and mean duration; the API reports the actual class factors and accepts explicit positive scenario overrides. The units are `(requests/min) × (GPU-min/request) = GPUs`. For `h` minutes ahead, the current implementation estimates:

\[
\widehat D_t(h)=\underbrace{\sum_c\lambda_{t,c}\,s(h)\,r_c}_{\text{expected future realtime load}}+
\underbrace{R_{known,t}(h)}_{\text{running requests with known end times}}+
\underbrace{Q_{known,t}}_{\text{current queued GPU-minutes divided by the 20-minute bridge}}+
\underbrace{F_t(h)}_{\text{accepted flexible commitment at that same minute}}.
\]

Here `s(h)` scales the rate by the known time-of-day factor. Running requests are included exactly if they remain active at the forecast minute. Already-observed queued requests are excluded from future-arrival EWMA and contribute a transparent average backlog-pressure term: sum of each queued request's `GPUs × min(duration, 20 min)`, divided by 20 min. This term is deliberately an approximation, not a promise that the dispatcher clears the queue within the bridge. The scheduled flexible GPU rate is paired with realtime load at the same future minute; do not add independently occurring maxima.

For each issued forecast window, store only predictions for minutes 5 through 24 ahead. When each minute becomes observable, record the positive underprediction residual `max(0, offered concurrent realtime GPUs + flexible commitment - predicted total demand)`. After 28 prior complete startup windows, use the empirical nearest-rank 95th percentile of their per-window maximum residuals as a single `M_t` for the bridge. Those windows are overlapping five-minute issues from this one synthetic replay, not independent days or real-data calibration. Before that threshold, use the explicit uncalibrated fallback `M_t=max(margin_floor_gpus, margin_fraction × predicted bridge peak)`; defaults are 4 GPUs and 15%. Both are configurable assumptions, not confidence guarantees. The protected upper demand is `U_t(h)=Dhat_t(h)+M_t`.

## 4. Former scalar warm target (superseded 2026-10-26)

The fixed-window scalar equation and operational rules in this historical section describe DEC-0006. They are retained to explain prior results and decisions only. Current activation planning and warm stock use the time-resolved wait-aware policy in section 11, which supersedes the former `W_stock=W_target+H_warm` relationship.

Let `A_t` be the number of active nodes, including spare capacity; `C_t=g A_t` is their total active GPU capacity. Let `W_t` be warm standby nodes, `B_t` booting nodes, `O_t` off nodes, with `A_t+W_t+B_t+O_t=N`. Current warm-to-active delay is `tau_w=5 min`; off-to-warm boot is 20 min; therefore total off-to-active delay is `tau_c=25 min`. An already booting node has an individual remaining ETA, counts once in the warm/boot pipeline, and cannot supply GPUs until boot plus warm activation finish.

For readiness diagnostics at offset `h`, the current state projects to:

\[
C_{ready,t}(h)=g\left(A_t+\sum_{i\in warming}\mathbf1[remaining_i\le h]+W_t\mathbf1[h\ge\tau_w]+\sum_{i\in booting}\mathbf1[remaining_i+\tau_w\le h]\right).
\]

Already-off nodes with no issued boot are not assumed to be ready just because an offset is long enough. The readiness gap is `max(0,U_t(h)-C_ready,t(h))`; installed-fleet overflow is separately `G_short,t(h)=max(0,U_t(h)-N×g)`. These are forecast diagnostics evaluated from recorded states/ETAs before a newly requested transition; starting a cold node does not retroactively remove a current bridge-window readiness gap.

For the adopted reserve calculation, inspect each future minute in the bridge interval `tau_w <= h < tau_c`, and pair forecast demand and flexible commitments at that same time:

\[
U_t(h)=\widehat D_t(h)+M_t(h),\qquad C_t=gA_t,
\]
\[
W_{target,t}=\left\lceil\frac{\max\left(0,\max_{\tau_w\le h<\tau_c} U_t(h)-C_t\right)}{g}\right\rceil.
\]

This is the **uncapped formula target** count of warm nodes needed in addition to current active capacity. Since it subtracts all active capacity, active spare GPUs are already included. If active capacity covers the upper demand, `W_target=0`; there is no artificial one- or two-node reserve minimum in the adopted equation. Separately, the controller's operational stock goal is `W_stock=W_target+H_warm`; `H_warm` is an explicit user-adjustable synthetic overhead (default one node) intended to leave an available warm buffer above formula-protected need. For warm-stock replenishment, ready `warm` nodes and `booting` nodes count once toward the reserve pipeline; `warming` nodes are already leaving standby for activation and are excluded. Only `warm` nodes count as ready stock. Each cold boot completion enters warm standby and is activated only by a subsequent capacity decision. The controller starts cold boots to replenish stock ahead of need, accounting for the 20-minute cold boot and current pipeline, while immediate workload needs can still promote warm nodes or leave the overhead temporarily below target. Report formula target, stock target, actual warm-ready, warm-stock replenishment pipeline, activation pipeline, ready deficit, fleet stock gap, formula fleet-node gap, protected GPU fleet overflow, and projected readiness gaps separately. The target does not make cold nodes ready instantly. If protected demand exceeds `N×g`, report the overflow; never clip the formula target and call it protected. Demand for `h<tau_w` is covered only by already-active spare capacity. Requests with a latency allowance below five minutes are not protected by the warm reserve alone.

The controller checks projected readiness by node state and recorded ETA, rather than treating `W_target` or `W_stock` as immediate capacity. Warm activation completes after five minutes; a cold boot issued now becomes warm after twenty minutes and only a later capacity decision activates it. This avoids treating boot completion as an automatic promotion. During a demand surge, warm nodes may be promoted before a replacement boot is ready; the replay reports this temporary stock deficit and any emergency readiness shortfall. Do not impose artificial dwell to pause the animation or delay accepted work. Current simulation's floor of active nodes is an independent configurable assumption for short-latency service, not a hidden warm-target minimum. The optional fixed-headroom input adds nodes to the inventory at scenario setup and leaves that total unchanged during replay; it is independent of Low/Normal/High arrival multipliers. Always-on control continues to start every inventory node active.

Scale up as soon as the upper forecast exceeds ready capacity in any interval. Scale down only after (U_h\) remains below the capacity after removing one warm node by a hysteresis gap (default 8 GPUs) for 30 continuous minutes, and honor a 30-minute minimum warm dwell. Never power down an occupied node. If whole-node control is selected, pack allocations onto the fewest active nodes that satisfy all GPU assignments; only empty nodes are eligible for transition. GPU-level scheduling remains logical, but the physical transition unit defaults to the node; independent GPU power gating is not assumed or claimed.

## 5. Queue priority, fairness, and overload

The proposed operational realtime queue is distinct from the existing flexible-job Pro earliness objective. Use a work-conserving, non-preemptive request dispatcher with two service classes: interactive ahead of batch initially; FIFO within class. A batch request waiting 15 minutes is promoted to the next interactive dispatch rank (configurable aging); backfill may skip an oversized head request only until it reaches that age, after which new starts reserve enough capacity for that head as current requests finish. Configurable per-class completion-latency allowances are scenario metrics, not guarantees. Long-running requests are not interrupted to make room.

Reject requests larger than fleet capacity. Bound the queue (default 256 requests) and reject new arrivals when full or when the causal wait estimate exceeds the request's latest-start limit. Count them as offered and rejected, including requested GPU-minutes; return a reason. If offered load exceeds active + warm + fleet capacity, report overload and missed latency/deadline metrics. Aging prevents priority starvation only under feasible load and finite request durations; it cannot guarantee service under sustained overload.

Report (W_i=start_i-a_i) queue wait and (T_i=completion_i-a_i) completion latency separately; class violation fraction is (#\{i:T_i>L_{c_i}\}/\#\{i\text{ offered in }c_i\}), counting rejected requests as violations. Report p50/p95 wait and completion latency, rejection rate, unfinished backlog, flexible GPU-hours delivered/unmet, and deadlines met. No numeric SLA is claimed.

## 6. Flexible scheduling and minute/hour coordination

The implemented comparison runs the existing hourly LP once for the fixed synthetic flexible-job set, with the configured Pro-priority policy and the original hourly reserved-realtime curve as a **capacity reservation**. The same schedule is held constant for all three node controllers. The LP still enforces each job's release/deadline window, exact GPU-hour demand, per-hour maximum parallelism, and the fleet capacity left after that reserved curve. If the LP is infeasible, no candidate job is marked accepted; the UI returns the solver reason and each candidate's unmet work. This is a conservative admission model: a real-time reservation is not also charged as real GPU activity in the dynamic energy trace.

At each minute, the scheduled hourly amount `x[j,h]` GPU-hours becomes a planned average rate `x[j,h]` GPUs for that hour. The minute commitment is `x[j,h] × 60` GPU-minutes; allocations stay within the LP job window and parallelism cap. Before a known commitment, reactive and forecast controllers request enough nodes to meet the larger planned flexible rate plus the reserved-realtime capacity by its ready time. The first-slot nodes are active at simulation start. A cold node requires 20 minutes to reach warm standby plus 5 minutes to become active; it is never counted ready instantly. Flexible allocations take first claim on active GPU capacity. A request can start only if running requests + its GPUs + the scheduled flexible rate remain within projected active capacity through that request's full non-preemptive duration. Requests that do not fit remain queued; they do not silently displace accepted flexible allocations. There is no checkpointing or flexible-job preemption because no runtime reallocation is done.

The prototype can still report an actual flexible shortfall if transitions or competing actual request work prevent the commitment from running; it records delivered/unmet GPU-hours, missed GPU-minutes, and each job's deadline result. LP admission is a planned-capacity check, not a promise that every dynamic trace meets every deadline. No accepted work is treated as complete unless its exact GPU-hour demand is delivered by its deadline. These rules are the implemented one-day coordination policy; replacing the fixed plan with rolling LP rescheduling remains future work.

For a future rolling LP, its capacity constraint should become, for each hourly slot (h),

\[
\sum_j x_{j,h}+\hat R^{upper}_{h}\Delta_{LP}\le C^{planned}_{h}\Delta_{LP},
\]

where (x_{j,h}) is GPU-hours, (hat R^{upper}_h) is the forecast upper bound in GPUs, and (C^{planned}_h) is active capacity plus only nodes with a known ready ETA by that slot. This rolling formulation is specified but not implemented: current v0 instead holds the one LP plan fixed and uses the LP's realtime curve as reserved capacity. A later implementation may re-solve only uncommitted future assignments at hour boundaries; it must preserve work already committed to the current interval, check remaining GPU-hours against deadlines after the upper realtime reserve, and surface infeasibility instead of admitting work that cannot finish.

At one-minute ticks, replay request arrivals/completions, fixed flexible-job GPU commitments, and node transitions. Flexible job execution is charged as actual allocated GPUs × minutes / 60, and the simulator checks exact delivered GPU-hours against declared deadlines. The current comparison performs no flexible-job preemption, migration, or reallocation, so it has no checkpoint interval or assumed checkpoint energy. If a future rolling scheduler changes an accepted commitment, it must configure checkpointability and measured/assumed preemption overhead (candidate sensitivity: 0/5/15 minutes), preserve the job's remaining work/window/parallelism, and prove deadline feasibility before publishing the changed schedule.

The minute queue uses actual running request GPUs for energy and offered/queued demand for capacity forecasts. A fixed reservation is not separately added to energy once request GPU activity and node states are modeled. Flexible workload, realtime GPU use, standby power, and boot transition are each counted once in the node/power trace.

### Replay data returned to the UI

Each policy response includes `replay.node_ids`, 1,440 ordered `replay.frames` (minute 0 through 1,439), and `replay.requests`. A frame records contemporaneous node `states`, total `used_gpus`, actual per-node `realtime_used_gpus` and `flexible_used_gpus`, and per-node IT `power_kw`, plus shared `facility_kw`, this minute's `grid_kwh`/`renewable_used_kwh`, and cumulative grid energy, cost, and emissions. The workload arrays align by index with `node_ids` and sum to total occupancy; UI categories Real-time, Flexible, Mixed, and Idle are derived only from those placement arrays, separately from power state. Node power excludes the shared 18 kW site overhead and PUE, while `facility_kw` includes both. A frame is captured after workload allocation and energy accounting for that minute, before transient flexible GPU slots are released. Request lifecycle records include ID, tier, arrival, GPU count, duration, start/completion/rejection timestamps, and horizon status; events with no occurrence by the 24-hour horizon are null. Playback must filter arrivals and lifecycle transitions by the selected simulated minute and must not present the precomputed future event list as already observed. Frame and final metric totals share the same accounting and are checked for energy balance. This replay payload is synthetic simulation output, not a live telemetry stream.

## 7. Facility energy, renewable supply, cost, and emissions

Use active node idle draw, warm-node draw, boot transition power, and active-GPU incremental power with non-overlapping definitions:

\[
P_{IT}(m)=P_{site}+N_A(m)P_{A0}+N_W(m)P_W+\sum_{n\in B}P_{boot,n}(m)+P_{\Delta GPU}G_{busy}(m).
\]

(P_{A0}) includes the active node's host and idle-GPU baseline; (P_{\Delta GPU}) is only incremental draw above that baseline. If node power is measured directly at utilization, replace (P_{A0}+P_{\Delta GPU}G) with the measured (P_{node}(state,utilization)) curve and do not sum both. Boot power is the actual interval draw during the transition; do not add a separate transition-energy charge on top of it. Facility demand is (P_{facility}=PUE\,P_{IT}). Per minute (Delta_m=1/60) hour, (L_m=P_{facility,m}\Delta_m) kWh.

Renewables use the existing 24-point synthetic supply profile as the continuity default; it peaks at 76 kWh in one-hour slots (equivalent to 76 kW average in that slot) and is not measured generation. At minute (m) inside hour (h), allocate (R_m=R_h\Delta_m/1\text{ hour}). Use renewables first: (E^R_m=\min(L_m,R_m)), grid import (E^G_m=L_m-E^R_m), curtailment (E^{curt}_m=R_m-E^R_m). Any cloud/day multiplier is seeded and labeled synthetic.

Report facility kWh, renewable used/curtailed kWh, grid-import kWh, cost CNY, and operational grid CO₂ separately. With an annual regional average factor, (CO2=\sum_m E^G_m EF_{grid}); use (0.5500\text{ kgCO₂/kWh}) for the dated 2023 East-China example, not a time-varying marginal factor. Official factor scope is operational CO₂, not lifecycle CO₂e. Do not claim hourly carbon optimization from a constant annual factor; hourly variation remains an explicitly synthetic sensitivity input unless an authoritative, matching hourly emissions dataset is sourced.

The Hourly schedule tab's node-controller charts now summarize the last completed Operations simulation result directly; they do not start a second run. Per-policy energy, grid cost, and emissions come from that run's 24 hourly accounting rows, while queue peaks are computed from its actual one-minute state trace. The view displays the run's seed, fleet, traffic, headroom, and warm-target settings so its provenance is explicit. It uses the dynamic simulator's synthetic renewable supply, fixed 0.55 kg CO₂/kWh grid factor, and illustrative CNY tariff; these are not the Hourly schedule scenario inputs or a customer bill. The run's request trace and dynamic flexible-job model remain separate from the LP's real-time reservation and flexible-job schedule.

### Xiamen/Fujian tariff interface and evidence

Each run selects tariff type (State Grid agent-purchase, direct market/wholesale, or retailer contract), effective month, voltage level, single/two-part category, time-of-use eligibility, and any applicable demand/capacity basic-charge option. The generic bill is:

\[
C_{bill}=\sum_m p_{energy,m}\,E^G_m + r_D P_{bill,max}+r_C S_{kVA}+C_{other},
\]

where energy rates are the applicable all-in CNY/kWh curve; (r_D) is CNY/kW-month times the billable maximum demand, (r_C) is CNY/kVA-month times transformer capacity, and the contract selects only the applicable basic-charge method. Use the official table's all-in time-of-use energy price **or** a decomposed procurement + network + line-loss + system-fee + levy calculation, never both; add a basic charge only if the contract uses a two-part tariff. Demand charges require the tariff's actual metering interval, which the one-minute demonstration must flag as an approximation unless the meter interval is configured.

Evidence checked 2026-10-24:

- Fujian Development and Reform Commission's TOU notice (issued 2023-11-28; effective 2024-01-01 for five years) sets 10:00–12:00, 15:00–20:00, 21:00–22:00 peak; 00:00–08:00 valley; other hours flat; +58% peak and −63% valley; July–September 11:00–12:00 and 17:00–18:00 super-peak at +80%. It applies to commercial/industrial users subject to market coordination and later policy changes. [Official Fujian NDRC notice](https://fgw.fujian.gov.cn/zwgk/fgzd/sfgwgfxwj/202311/t20231129_6309872.htm).
- A dated October 2026 State Grid Fujian agent-purchase table published on Dehua County Government's portal gives a representative 1–10(20) kV single-part example: flat 0.62185675, peak 0.83855171, valley 0.38648119 CNY/kWh; the same row's components are 0.373612 agent purchase, 0.013021 line-loss, 0.163300 distribution, 0.02766875 funds/levies, and 0.044255 system fees. The 1–10(20) kV two-part example is flat 0.58045675, peak 0.79715171, valley 0.34508119 CNY/kWh, with shown demand/capacity rates 40 CNY/kW-month and 25 CNY/kVA-month. [Dated official-government publication of State Grid Fujian's October 2026 table](https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm). This is a provincial agent-purchase example, not confirmation of this project's Xiamen customer's tariff or eligibility.
- Fujian's 2026 market-trading plan says 10 kV and above commercial/industrial users are in principle direct-market users; below 10 kV direct-market participation is encouraged. Market prices are formed through contracts/market; during spot-market operation market users' time-of-use prices are market-formed, while certain retail packages follow their contract. The plan says market trading prices exclude capacity charges. [2026 Fujian market plan, issued 2025-12-09](https://fgw.fujian.gov.cn/zfxxgkzl/zfxxgkzc/gfwjk/202512/t20251210_7044850.htm).
- MEE and NBS published 2023 regional electricity average CO₂ factors on 2025-12-31; East China is 0.5500 kgCO₂/kWh. This annual factor is not an hourly marginal factor. [Official 2023 electricity factor announcement](https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html), [MEE technical explanation](https://www.mee.gov.cn/ywdt/zbft/202601/t20260105_1139911.shtml).

No exact Xiamen customer rate is selected: customer voltage, single/two-part status, market participant type, retail package, metering interval, and monthly contract price are unknown. The cited representative table is not a substitute for a customer's bill. The simulator must expose the selected tariff source and mark agent-purchase rates as proxy/example when those fields are unknown; it must not call a wholesale, retail, or proxy rate simply “the Xiamen tariff.”

## 8. Worked example for the superseded scalar policy (historical; illustrative only)

For (N=12), (g=8), and eight active nodes, active capacity including any spare is (C_t=64) GPUs. Suppose the maximum same-minute forecast during 5 <= h < 25 is 78 GPUs, and the current fallback margin is 10 GPUs. Then U_t=78+10=88 and the adopted target is W_target=ceil((88-64)/8)=3 warm nodes. If one node is already warm, two additional reserve nodes are needed; any off nodes started now remain booting and cannot be treated as ready in this 25-minute window. If protected demand is at or below active capacity, the target is zero. If upper demand were 101 GPUs, the uncapped target would be ceil((101-64)/8)=5 nodes; with only four nodes outside the active set, report one node of target shortfall and a 5-GPU fleet shortfall. Do not label that clipped fleet as protected.

## 9. Reproducible evaluation and acceptance criteria

Compare the exact same seeded offered-request trace, accepted flexible-job input set, inventory, power coefficients, renewables, tariff, grid factor, and accounting across: (1) an additional always-on, FIFO/next-fit, flexible-work ASAP baseline with no energy-aware timing; (2) always-on with the shared Pro-priority LP schedule; (3) reactive scale-on from current queue/active demand with the same warm/cold delays and no forecast; and (4) causal forecast reserve with the same queue and transition model. The unscheduled baseline uses only jobs admitted by the shared LP gate, then greedily executes those exact jobs at their earliest available hour up to each job parallelism cap and fleet capacity. It does not optimize energy, price, or carbon. If actual baseline delivery or request terminal states differ from a selected controller, show raw percentages but mark service as non-comparable. Use separate recorded seeds for traffic, burst timing, renewable variation, and optimizer tie-breaking. Keep an untouched future period for rolling-origin forecast/error evaluation.

Report per-policy: node-state and transition timelines; offered/running/queued/rejected GPUs; forecast and upper-margin error by horizon; target/actual warm nodes and any readiness/fleet shortfalls; request p50/p95 wait/completion latency, class violation/rejection rates, backlog; flexible work completed/unmet and deadlines met; facility/renewable/grid kWh, curtailment, CNY bill components, grid CO₂, and transition counts. For each controller versus the no-energy-scheduling baseline, calculate electricity savings from facility kWh, grid-import change separately, cost reduction, and emissions reduction as `(baseline - controller) / baseline × 100`; null is required for zero/unavailable denominators, and negative values mean increases. Report service comparability plus completed/rejected/backlog, wait/completion latency, and flexible delivered/deadline differences next to energy percentages. Do not call lower-energy work-dropping a comparable savings win or fabricate results.

Sensitivity/failure cases: arrival ×0.5/1/1.5/2; hidden burst ×1/2/3/4; forecast α and 90/95/99% margin; warm/cold delays ×0.5/1/2; standby power 15/25/50% active-idle; fleet and GPU/node size; no renewables; tariff type/voltage/month and demand charges; longer service tails; urgent requests faster than warm activation; demand above fleet; infeasible flexible deadlines. Verify state conservation, causality (no future input), request GPU conservation, reserve/shortfall arithmetic, deadline preservation, readiness timing, energy balance, and unit conversions before using scenario results.

## 10. Implementation decision boundary

This specification finalizes the simulation policy under explicit user authorization to finish the policy and begin implementation. It does not mean the numerical defaults are measured or separately approved. Replace them with hardware docs, telemetry, and account-specific tariff data when available. Do not use the simulator as an operational controller; overload is a reported failure, not a service guarantee.

## 11. Current wait-aware readiness policy (2026-10-26)

**Current decision (DEC-0007):** the user clarified, “i meant, improve the warm reserve calculation policy to minimize waiting time. then, give me a full explanation of all parts of the simulation.” This supersedes the former scalar-only operating policy in sections 4 and 8. The scalar formula is retained as a diagnostic for continuity; it no longer sets activation timing or the operational warm-stock target. The user explicitly authorized changing the reserve calculation. The numerical choices below are implementation assumptions made to satisfy that goal, not separate user approvals or proof of a global optimum.

**Current decision (DEC-0008, 2026-10-26):** the user further requested, “there should alwaysbe a warm standby” and “for real time, requests should instantly fill the warm standby and get processed,” and later authorized policy adjustment and requested a forecast-model summary. Warm-ready nodes are now promoted to active in the same simulation minute (`tau_w=0`), explicitly as an idealized model assumption; OFF-to-warm cold boot remains 20 minutes. The Forecast default warm-stock target is two nodes (0–8 configurable), chosen as a small buffer so one ready node may remain when another is consumed. Forecast readiness plans start cold boots first for demand 20+ minutes away to preserve warm standby; immediate arrivals are work-conservingly dispatched into idle active capacity and then ready warm nodes. A configured target is best-effort: requests are never held to keep the target green, and fleet overload/stock depletion remains visible. Accepted flexible jobs now run after real-time work, Pro-first then earliest deadline, using remaining active GPUs up to `max_gpus` and catching up anywhere inside the declared window. No request preemption occurs. LP admission remains a feasibility screen, not a runtime deadline guarantee; delivered/unmet GPU-hours and deadlines expose any miss. The user's exact request authorizes the policy direction, not these numerical constants or a global optimum.

**Current decision (DEC-0009, 2026-10-26):** the user requested, “for these, if there are queued tasks just fill the reserves.” After each real-time dispatch pass, the warm-stock target is `max(configured warm overhead, ceil(total queued request GPUs / GPUsPerNode))`, capped at fleet size. This queue-triggered refill starts OFF nodes toward warm stock immediately, but they are not ready until the 20-minute cold boot completes. The target returns to the configured overhead when the queue clears; already-started stock boots are not canceled. Queue GPU totals are treated as concurrent demand, so reserve staging can exceed the actual queue's eventual concurrency. This keeps queued work visible and replenishes reserve independently from activation boots, but it can raise power use during backlogs.

Every five minutes the forecast controller constructs `D_upper(h)` for future minute offsets 0–40:

```text
D_upper(h) = expected new-arrival GPU concurrency
           + known running GPUs with completion after t+h
           + queued requests placed into earliest feasible non-preemptive slots
           + accepted flexible GPU rate at that same minute
           + current uncertainty margin
required active nodes(h) = ceil(D_upper(h) / GPUsPerNode)
```

Expected arrivals use only the causal per-class five-minute EWMA, the declared synthetic diurnal multipliers, and the rounded-duration survival distribution. The arrival term excludes already-running and already-queued work; those are separately represented. The queued planner uses class/age priority, exact request sizes and durations, known running completions, flexible commitments, expected new-arrival concurrency, and currently issued node ETAs to find earliest feasible slots. It is a greedy capacity approximation rather than a replay of the actual future dispatcher. Peaks are paired minute by minute, so a flexible peak at one time is not added to a real-time peak from a different time.

The controller cold-boots nodes no later than 20 minutes before target readiness. Warm nodes have zero modeled promotion delay. Active-readiness planning counts only active/warming nodes and cold activation pipelines; it does not mistake a warm-stock boot for immediately active capacity. Warm stock is accounted separately: ready `warm` nodes count as ready; cold nodes booting specifically for warm replacement count only in the replenishment pipeline; nodes booting for activation are not counted as reserve. This prevents double-counting. The independently configured warm-overhead target defaults to two nodes and accepts 0–8 nodes; the actual ready count can be below target while replacement cold boots run. The existing active floor remains an independent service assumption (25% by default). No request is intentionally delayed to preserve standby.

Forecast margin defaults remain EWMA alpha `0.3`, fallback floor `4 GPUs`, and fallback fraction `15%`. Until 28 fully observed rolling 20-minute forecast windows exist, the margin is `max(floor, fraction × predicted demand)`. Afterwards it is the 95th percentile of the per-window maximum *positive residual* between observed demand and the raw forecast. A window closes only after all 20 future minutes have actually elapsed. This causal update is based only on the current synthetic day, whose overlapping windows are neither independent nor real calibration data. It may still underestimate surprise surges or overreact to a synthetic error; it is not a confidence bound.

An operational gap is `max(0, D_upper(h) - projected active GPUs(h))` and the fleet gap is `max(0, D_upper(h) - installed GPUs)`. They remain visible even if stock cannot be maintained. The target prefers fewer predicted startup waits, but does not promise zero waiting; an always-on fleet is the lower-wait reference where the offered work fits, at greater idle power. Under constrained bursts, the fleet and parallelism remain the limiting factors.

Verification and actual before/after outcomes for identical request traces are recorded in [the wait-aware comparison report](../results/wait-aware-forecast-comparison-2026.md) and [its trace-hashed metrics](../results/wait-aware-forecast-comparison-2026.json). The source-grounded end-to-end explanation is [simulation-explained.md](../docs/simulation-explained.md). Production workload comparisons should be read with the realism limitations and primary references in that guide; no production traces have been imported or used for calibration.

### Interpreting immediately available reserve and forecast gaps

The per-node state chart encodes power state only: an active node can contain occupied GPUs and idle GPUs. At each selected minute, `active_spare_gpus = max(0, active_nodes × GPUsPerNode − running_real_time_GPUs − running_flexible_GPUs)` is idle active capacity, available immediately. `warm_ready_capacity_gpus = warm_nodes × GPUsPerNode` is separate standby that can be promoted at zero modeled minutes. `dispatchable_capacity_gpus` is their sum. Booting/off nodes do not count as ready. Real-time requests may consume warm standby; current queue wait is observed service delay, whereas projected readiness shortfall is forecast-versus-ETA and does not itself mean a request waited.

The final default seed-2026 / Normal / 32×8 / zero-added-headroom Forecast replay generated 2,109 requests. Thirty requests arrived during 01:00–01:59; each started in its arrival minute and none of the day's requests waited. All six flexible jobs met deadlines. At 01:10 there were 15 active nodes, 28 idle active GPUs, and two warm-ready nodes (16 more GPUs promotable immediately), for 44 GPUs of ready-now capacity. Day totals were 2,914.217 facility kWh, 2,402.217 grid kWh, and ¥1,397.26 illustrative energy cost. This replaces the prior no-reserve interpretation and is recorded in `results/instant-warm-policy-comparison-2026.*`; it does not guarantee reserve during high sustained or surprise demand.

## Hourly schedule policy graphs — 2026-10-26

The Hourly schedule tab's controller graphs now summarize the last completed Operations simulation result directly; they no longer start a separate run or substitute schedule-case assumptions. For each Always-on, Reactive, and Forecast policy they render the simulator's 24 hourly grid-import, renewable-use, facility-energy, grid-emissions, and CNY grid-cost rows, plus the maximum queued-request count from that run's minute-level state trace in each hour. The chart context shows the exact run's seed, nodes, GPUs per node, and traffic profile. Grid cost uses the simulator's illustrative CNY tariff, not a customer bill; grid emissions use its fixed 0.55 kg CO₂/kWh factor. This replay remains separate from the legacy hourly LP workload and its schedule. The queue peak is context from observed simulation states, not a latency metric. A 1366×768 desktop QA review found no page overflow, clipped text, browser runtime errors, broken images, or missing image alt text; mobile QA was intentionally skipped.
