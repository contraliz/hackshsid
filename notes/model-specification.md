# GridShift Dynamic Co-Scheduling Model

**Status:** Policy design finalized under the user's 2026-10-24 instruction to complete the policy and begin simulation implementation. Numerical settings are agent-selected, configurable illustrations—not separately user-approved facts, measurements, service guarantees, or measured savings. This document distinguishes the existing hourly prototype, the implemented minute-scale request simulator, and policy elements still awaiting implementation. No real infrastructure should be controlled from this classroom model.

**Current prototype:** `backend/data.py` still supplies hourly synthetic prices, renewables, and `REALTIME_GPUS`; `backend/scheduler.py` still runs its hourly LP and shared evaluator; `backend/priority_queue.py` still replays user-supplied requests against that fixed reservation. These inputs are not a request history or warm-node telemetry. The operational simulator described here is additive; it does not reinterpret the fixed reservation as warm capacity or silently change the existing hourly API/defaults. See [README](../README.md) and [MVP model guide](mvp-model-and-execution-guide.md).

**Implemented v0:** `backend/dynamic_simulation.py` exposes `POST /api/dynamic-simulation`, called by the Node power-state panel in the app. Default inventory is 32 homogeneous nodes × 8 GPUs = 256 installed GPUs; the UI offers an explicit illustrative 12 × 8 = 96 GPU reference. Initial state for a dynamic policy is 16 active, 2 warm, and the remainder off (for fleets with fewer than 18 nodes the states are clipped to the available inventory); a configurable 25% active-node floor protects short-latency work, but is itself an unmeasured assumption. A seeded one-day Poisson trace uses the class rates, GPU counts and triangular durations below. Every five minutes the forecast controller updates per-class requests/minute EWMAs from the preceding completed arrival bucket. It converts rates using explicitly exposed synthetic GPU-minutes/request factors, accounts for known running and queued work, adds the flexible commitment at each same future minute, and applies the adopted bridge-window warm-reserve equation in Sections 3–4. The default fallback margin is `max(4 GPUs, 15% × predicted bridge-window peak)` until 28 prior issued startup-window errors mature; those errors are still synthetic and overlapping within one scenario, not real history or independent calibration. The same generated trace is replayed under always-on, reactive, and forecast-reserve policies. Warm-to-active takes 5 min; cold boot to warm takes 20 min, so off-to-active is 25 min total. Nodes remain unavailable while transitioning. Queue control activates warm nodes to satisfy queued demand; forecast control also replenishes its target warm reserve. Scale-down waits 30 idle minutes and never powers down an occupied node. The operational queue prioritizes interactive requests but promotes batch work after 15 minutes; an aged batch request reserves starts until it fits, preventing indefinite backfill. Running requests are non-preemptive; oversized requests and arrivals past the 256-request queue bound are rejected explicitly. With an explicit `request_trace`, the causal arrival-rate prior starts at zero; the default synthetic generator instead seeds its first bucket from its declared baseline.

The minute simulator's IT power is `18 kW fixed overhead + 1.0 kW × active nodes + 0.25 kW × warm nodes + 1.2 kW × booting nodes + 0.35 kW × (running request GPUs + running flexible GPUs)`, multiplied once by PUE 1.25. These are synthetic placeholders. It uses the existing synthetic hourly renewable profile, the dated Fujian tariff example below as a CNY proxy, and the cited East-China annual-average CO₂ factor. Its metrics and assumptions appear in the API response and UI. The dynamic comparison now obtains one fixed Pro-priority hourly LP schedule and shares it across always-on, reactive, and forecast controllers. LP capacity admission retains the existing reserved-realtime curve as a capacity reservation; generated request work replaces that placeholder in minute-level power accounting, so reservation is not counted as extra GPU activity. The minute controller starts capacity ahead of known accepted commitments, commits flexible GPU-minutes before dispatching requests, and declines any request that would consume capacity required by its scheduled work over the request's non-preemptive duration. LP-infeasible jobs are labeled not admitted; runtime commitment shortfall and per-job deadline misses are reported. The API accepts optional validated `request_trace` and `flexible_jobs` arrays for controlled scenarios; absent overrides, it uses the seeded default trace and existing LP job set. No runtime flexible reallocation or preemption is implemented. Historical forecast-error calibration, node-specific measured power curves, and tariff selection for a known Xiamen customer remain data/model gaps. These are not assumed features.

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

Multiply each class's base arrival rate by a synthetic time-of-day factor: 0.35 from 00:00–06:00; 0.60 from 06:00–09:00; 1.00 from 09:00–17:00; 1.50 from 17:00–22:00; 0.70 from 22:00–24:00. Seeded Poisson arrivals and seeded discrete GPU/duration draws make each trace reproducible. Add seeded 15-minute bursts at 3× the class rate in a configurable fraction of runs (default 25%); future burst events are hidden from the forecaster unless an event calendar is actually known at forecast time. These values do not describe observed Xiamen traffic.

Flexible ML/batch work keeps the existing job representation: GPU-hour demand, release/deadline window, maximum parallel GPUs, and accepted/committed status. In the new model, defaults are workload fixtures, not calibrated benchmarks. Preserve (w_j) and (d_j) for every accepted job; report an admission rejection before acceptance if its constraints are infeasible. An accepted job is never silently dropped.

## 3. Causal forecast and uncertainty

At a minute decision time `t`, the EWMA is updated every five-minute bucket using only arrivals observed in the **just completed** bucket. For class `c`, `n[t,c]` is its count in the completed bucket, `Delta=5 min`, and `lambda[t,c]` is requests/minute:

\[
\lambda_{t+1,c}=\alpha\frac{n_{t,c}}{\Delta}+(1-\alpha)\lambda_{t,c}.
\]

At the default `alpha=0.30`, the first default-synthetic bucket starts from the configured generator baseline adjusted by its known time-of-day factor. An explicit `request_trace` starts at zero. Future traffic uses the known synthetic time-of-day profile; hidden future arrivals and burst draws are never read by the forecast. These generator values are assumptions, not observations.

For each request class, `r_c` is GPU-minutes/request. The default value is the product of the synthetic generator's mean requested GPUs and mean duration; the API reports the actual class factors and accepts explicit positive scenario overrides. The units are `(requests/min) × (GPU-min/request) = GPUs`. For `h` minutes ahead, the current implementation estimates:

\[
\widehat D_t(h)=\underbrace{\sum_c\lambda_{t,c}\,s(h)\,r_c}_{\text{expected future realtime load}}+
\underbrace{R_{known,t}(h)}_{\text{running requests with known end times}}+
\underbrace{Q_{known,t}}_{\text{current queued GPU-minutes divided by the 20-minute bridge}}+
\underbrace{F_t(h)}_{\text{accepted flexible commitment at that same minute}}.
\]

Here `s(h)` scales the rate by the known time-of-day factor. Running requests are included exactly if they remain active at the forecast minute. Already-observed queued requests are excluded from future-arrival EWMA and contribute a transparent average backlog-pressure term: sum of each queued request's `GPUs × min(duration, 20 min)`, divided by 20 min. This term is deliberately an approximation, not a promise that the dispatcher clears the queue within the bridge. The scheduled flexible GPU rate is paired with realtime load at the same future minute; do not add independently occurring maxima.

For each issued forecast window, store only predictions for minutes 5 through 24 ahead. When each minute becomes observable, record the positive underprediction residual `max(0, offered concurrent realtime GPUs + flexible commitment - predicted total demand)`. After 28 prior complete startup windows, use the empirical nearest-rank 95th percentile of their per-window maximum residuals as a single `M_t` for the bridge. Those windows are overlapping five-minute issues from this one synthetic replay, not independent days or real-data calibration. Before that threshold, use the explicit uncalibrated fallback `M_t=max(margin_floor_gpus, margin_fraction × predicted bridge peak)`; defaults are 4 GPUs and 15%. Both are configurable assumptions, not confidence guarantees. The protected upper demand is `U_t(h)=Dhat_t(h)+M_t`.

## 4. Warm target, readiness, and power-state control

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

This is the **uncapped target count** of warm nodes needed in addition to current active capacity. Since it subtracts all active capacity, active spare GPUs are already included. If active capacity covers the upper demand, `W_target=0`; there is no artificial one- or two-node reserve minimum. Existing warm, warming, and booting nodes count once toward the reserve pipeline; state/ETA still determines when they provide active GPUs. Any remaining deficit recruits only available off nodes and marks them booting; the target itself does not make cold nodes ready instantly. Report the uncapped target, realizable target, fleet node shortfall, GPU fleet shortfall, and readiness shortfalls separately. If protected demand exceeds `N×g`, report the overflow; never clip the target and call it protected. Demand for `h<tau_w` is covered only by already-active spare capacity. Requests with a latency allowance below five minutes are not protected by the warm reserve alone.

The controller checks projected readiness by node state and recorded ETA, rather than treating `W_target` as immediate capacity. Warm activation completes after five minutes; a cold boot issued now becomes warm after twenty minutes and active after twenty-five. Existing one-minute dwell/hysteresis rules remain separate from the mathematical target: the calculated target may be zero while an already warm node remains temporarily on due to dwell. Current simulation's floor of active nodes is an independent configurable assumption for short-latency service, not a hidden warm-target minimum.

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

Each policy response includes `replay.node_ids`, 1,440 ordered `replay.frames` (minute 0 through 1,439), and `replay.requests`. A frame records contemporaneous node `states`, `used_gpus`, and per-node IT `power_kw`, plus shared `facility_kw`, this minute's `grid_kwh`/`renewable_used_kwh`, and cumulative grid energy, cost, and emissions. The node arrays align by index with `node_ids`; node power excludes the shared 18 kW site overhead and PUE, while `facility_kw` includes both. A frame is captured after workload allocation and energy accounting for that minute, before transient flexible GPU slots are released. Request lifecycle records include ID, tier, arrival, GPU count, duration, start/completion/rejection timestamps, and horizon status; events with no occurrence by the 24-hour horizon are null. Playback must filter arrivals and lifecycle transitions by the selected simulated minute and must not present the precomputed future event list as already observed. Frame and final metric totals share the same accounting and are checked for energy balance. This replay payload is synthetic simulation output, not a live telemetry stream.

## 7. Facility energy, renewable supply, cost, and emissions

Use active node idle draw, warm-node draw, boot transition power, and active-GPU incremental power with non-overlapping definitions:

\[
P_{IT}(m)=P_{site}+N_A(m)P_{A0}+N_W(m)P_W+\sum_{n\in B}P_{boot,n}(m)+P_{\Delta GPU}G_{busy}(m).
\]

(P_{A0}) includes the active node's host and idle-GPU baseline; (P_{\Delta GPU}) is only incremental draw above that baseline. If node power is measured directly at utilization, replace (P_{A0}+P_{\Delta GPU}G) with the measured (P_{node}(state,utilization)) curve and do not sum both. Boot power is the actual interval draw during the transition; do not add a separate transition-energy charge on top of it. Facility demand is (P_{facility}=PUE\,P_{IT}). Per minute (Delta_m=1/60) hour, (L_m=P_{facility,m}\Delta_m) kWh.

Renewables use the existing 24-point synthetic supply profile as the continuity default; it peaks at 76 kWh in one-hour slots (equivalent to 76 kW average in that slot) and is not measured generation. At minute (m) inside hour (h), allocate (R_m=R_h\Delta_m/1\text{ hour}). Use renewables first: (E^R_m=\min(L_m,R_m)), grid import (E^G_m=L_m-E^R_m), curtailment (E^{curt}_m=R_m-E^R_m). Any cloud/day multiplier is seeded and labeled synthetic.

Report facility kWh, renewable used/curtailed kWh, grid-import kWh, cost CNY, and operational grid CO₂ separately. With an annual regional average factor, (CO2=\sum_m E^G_m EF_{grid}); use (0.5500\text{ kgCO₂/kWh}) for the dated 2023 East-China example, not a time-varying marginal factor. Official factor scope is operational CO₂, not lifecycle CO₂e. Do not claim hourly carbon optimization from a constant annual factor; hourly variation remains an explicitly synthetic sensitivity input unless an authoritative, matching hourly emissions dataset is sourced.

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

## 8. Worked reserve example (illustrative only)

For (N=12), (g=8), and eight active nodes, active capacity including any spare is (C_t=64) GPUs. Suppose the maximum same-minute forecast during 5 <= h < 25 is 78 GPUs, and the current fallback margin is 10 GPUs. Then U_t=78+10=88 and the adopted target is W_target=ceil((88-64)/8)=3 warm nodes. If one node is already warm, two additional reserve nodes are needed; any off nodes started now remain booting and cannot be treated as ready in this 25-minute window. If protected demand is at or below active capacity, the target is zero. If upper demand were 101 GPUs, the uncapped target would be ceil((101-64)/8)=5 nodes; with only four nodes outside the active set, report one node of target shortfall and a 5-GPU fleet shortfall. Do not label that clipped fleet as protected.

## 9. Reproducible evaluation and acceptance criteria

Compare the exact same seeded offered-request trace, accepted flexible-job input set, inventory, power coefficients, renewables, tariff, grid factor, and accounting across: (1) an additional always-on, FIFO/next-fit, flexible-work ASAP baseline with no energy-aware timing; (2) always-on with the shared Pro-priority LP schedule; (3) reactive scale-on from current queue/active demand with the same warm/cold delays and no forecast; and (4) causal forecast reserve with the same queue and transition model. The unscheduled baseline uses only jobs admitted by the shared LP gate, then greedily executes those exact jobs at their earliest available hour up to each job parallelism cap and fleet capacity. It does not optimize energy, price, or carbon. If actual baseline delivery or request terminal states differ from a selected controller, show raw percentages but mark service as non-comparable. Use separate recorded seeds for traffic, burst timing, renewable variation, and optimizer tie-breaking. Keep an untouched future period for rolling-origin forecast/error evaluation.

Report per-policy: node-state and transition timelines; offered/running/queued/rejected GPUs; forecast and upper-margin error by horizon; target/actual warm nodes and any readiness/fleet shortfalls; request p50/p95 wait/completion latency, class violation/rejection rates, backlog; flexible work completed/unmet and deadlines met; facility/renewable/grid kWh, curtailment, CNY bill components, grid CO₂, and transition counts. For each controller versus the no-energy-scheduling baseline, calculate electricity savings from facility kWh, grid-import change separately, cost reduction, and emissions reduction as `(baseline - controller) / baseline × 100`; null is required for zero/unavailable denominators, and negative values mean increases. Report service comparability plus completed/rejected/backlog, wait/completion latency, and flexible delivered/deadline differences next to energy percentages. Do not call lower-energy work-dropping a comparable savings win or fabricate results.

Sensitivity/failure cases: arrival ×0.5/1/1.5/2; hidden burst ×1/2/3/4; forecast α and 90/95/99% margin; warm/cold delays ×0.5/1/2; standby power 15/25/50% active-idle; fleet and GPU/node size; no renewables; tariff type/voltage/month and demand charges; longer service tails; urgent requests faster than warm activation; demand above fleet; infeasible flexible deadlines. Verify state conservation, causality (no future input), request GPU conservation, reserve/shortfall arithmetic, deadline preservation, readiness timing, energy balance, and unit conversions before using scenario results.

## 10. Implementation decision boundary

This specification finalizes the simulation policy under explicit user authorization to finish the policy and begin implementation. It does not mean the numerical defaults are measured or separately approved. Replace them with hardware docs, telemetry, and account-specific tariff data when available. Do not use the simulator as an operational controller; overload is a reported failure, not a service guarantee.
