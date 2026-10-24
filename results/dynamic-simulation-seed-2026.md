# Dynamic simulation receipt — seed 2026

Generated 2026-10-24 from `backend.dynamic_simulation.run_dynamic_comparison` at commit `954ee5d33eedf09869743067f4c645389671040d`. This is one synthetic scenario, not a forecast, measurement, or deployment result. The 32×8 run uses a single seeded trace of 2,109 requests with peak unconstrained offered concurrency of 107 GPUs. It applies the same 3,060 GPU-hour LP-admitted flexible workload to every controller and the baseline. All approaches complete 2,102 requests, leave 7 running at the horizon, reject none, and deliver all 3,060 flexible GPU-hours by all six deadlines. Each accounts for 33,028 realtime GPU-minutes plus 183,600 flexible GPU-minutes = 216,628 GPU-minutes in variable GPU power.

## Same-input results

| Approach | Facility kWh | Grid kWh | Renewable used / curtailed kWh | Cost proxy CNY | Grid CO₂ kg | Completed / queued / running / rejected | Mean wait / P95 wait min | Mean completion latency min | Response allowance met / completed | Flexible delivered GPU·h | Deadlines met |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Unscheduled baseline** — all-on, FIFO/next-fit requests, flexible jobs ASAP | 3,079.579 | 2,567.579 | 512.000 / 0 | 1,508.613 | 1,412.169 | 2,102 / 0 / 7 / 0 | 5.43 / 39 | 12.53 | 405 / 2,102 | 3,060 | 6 / 6 |
| Existing always-on policy | 3,079.579 | 2,567.579 | 512.000 / 0 | 1,510.261 | 1,412.169 | 2,102 / 0 / 7 / 0 | 0 / 0 | 7.10 | 486 / 2,102 | 3,060 | 6 / 6 |
| Reactive controller | 2,883.626 | 2,371.626 | 512.000 / 0 | 1,374.940 | 1,304.394 | 2,102 / 0 / 7 / 0 | 0 / 0 | 7.10 | 486 / 2,102 | 3,060 | 6 / 6 |
| Causal forecast reserve | 2,890.767 | 2,378.767 | 512.000 / 0 | 1,380.123 | 1,308.322 | 2,102 / 0 / 7 / 0 | 0 / 0 | 7.10 | 486 / 2,102 | 3,060 | 6 / 6 |

## Changes relative to the unscheduled baseline

Percent is `(baseline - controller) / baseline × 100`. Positive values are reductions; negative values are increases. Facility kWh is the electricity-savings basis; grid imports are reported separately. All three comparisons are marked **service comparable** because every request has the same terminal state and the same admitted flexible jobs have matching delivery/deadline outcomes. Response time still differs: the no-energy-scheduling baseline has 5.43-minute mean wait, 39-minute P95 wait, and 12.53-minute completion latency; the optimized-policy rows show 0-minute mean/P95 wait and 7.10-minute mean completion latency. Thus service-comparable means same terminal outcomes and flexible work, not identical latency.

| Controller | Facility electricity reduction | Grid-import reduction | Cost reduction | Grid-emissions reduction | Service comparison |
|---|---:|---:|---:|---:|---|
| Always-on | 0.000% | 0.000% | **−0.109%** (cost increase) | 0.000% | Comparable; same terminal outcomes; response metrics above |
| Reactive | 6.363% | 7.632% | 8.861% | 7.632% | Comparable; same terminal outcomes; response metrics above |
| Forecast reserve | 6.131% | 7.354% | 8.517% | 7.354% | Comparable; same terminal outcomes; response metrics above |

The forecast reports a peak **predicted upper-demand fleet gap** of 28.13 GPUs over 85 five-minute intervals, peak readiness gap 73.62 GPUs over 111 sampled intervals, and maximum uncapped warm target 26 nodes with a maximum target/fleet gap of 4 nodes. The observed trace itself never exceeded the 256-GPU installed fleet and every request reached the same terminal state as baseline. The forecast figures are conservative model warnings from synthetic rates, queued/running approximations, flexible commitments and the margin; they are not realized service failures or promises. The controller comparison does not establish which policy is preferable.

## 96-GPU reference and flexible-work check

With 12×8=96 GPUs and the default six-job / 3,060-GPU-hour workload, the existing Pro-priority LP reports **infeasible** admission. The same LP-gated accepted set is therefore empty for all approaches; all 3,060 candidate GPU-hours are explicitly reported as not admitted/unmet, rather than counting them in energy. The same trace peaks at 107 GPUs (11 GPUs above the fleet for 4 minutes). These values are not a like-for-like comparison with the 256-GPU run because the flexible input could not be admitted.

A focused 12×8 case with one 20-GPU-hour job and a 2-hour deadline plus a same-input burst of twenty simultaneous 8-GPU/30-minute requests confirms all three controllers deliver the accepted job on time without missed flexible GPU-minutes. A 100-GPU-hour one-hour candidate is explicitly rejected as LP-infeasible. A separate 20-GPU-hour case verifies the unscheduled baseline receives the same LP-admitted job and executes it ASAP while meeting the same deadline.

## Adopted reserve calculation and assumptions

The user explicitly requested: “ingest this and apply this to the warmed reserve calculation”. For 8 GPUs/node, 8 active nodes and same-minute forecast peak 78 GPUs plus 10-GPU margin, the adopted target is `ceil((78 + 10 - 64) / 8) = 3` warm nodes. It subtracts all active GPU capacity (including spare), pairs realtime and flexible workload at the same future minute, and reports an uncapped target/fleet/readiness shortfall. The bridge is `5 <= h < 25 min`: warm-to-active is 5 minutes; cold-to-warm is 20 minutes, so fully-off-to-active is 25 minutes total. If active capacity already covers upper demand, the mathematical target is zero.

The forecast is a five-minute causal per-class arrival-rate EWMA (alpha 0.30 by default) multiplied by synthetic GPU-minutes/request factors: interactive 7.5 and batch 50.0. Current running requests are included by known completion time; queued GPU-minutes are capped to the 20-minute bridge then averaged across that bridge; flexible commitments are added at the same future minute. Error margin uses nearest-rank 95th percentile of 28 matured, overlapping startup-window residual maxima once available; until then it uses `max(4 GPU, 15% × predicted bridge-window peak)`. The history is from this synthetic run, not measured independent multi-day history. These workload factors, fallback settings and node delays are illustrative scenario assumptions, not hardware facts or calibrated forecasts. The source message was a normalized re-paste of earlier assistant proposal text, SHA-256 `2C80A80EDF4111A756BDD426634F9AFD74187FC5CA12EF40B515BC9408C68457`; it is not empirical evidence. DEC-0006 records the user's adoption instruction; see AgentMem `risks` for provenance.

*Cost uses the October 2026 State Grid Fujian 1–10(20) kV single-part agent-purchase curve as a CNY proxy; this is not a verified Xiamen customer's tariff or eligibility. [Official October 2026 table hosted by Dehua County Government](https://www.dehua.gov.cn/zwgk/zdxxgk/ggqsy/gd/202610/t20261010_3334560.htm).

**Grid CO₂ uses the official 2023 East-China annual average, 0.5500 kgCO₂/kWh; this is not hourly marginal emissions or CO₂e. [MEE/NBS announcement](https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/t20251231_1139517.html).

The full versioned model, equations, source dates, limitations and implementation boundary are in [`notes/model-specification.md`](../notes/model-specification.md). Same-input batch outputs are available through [`docs/operational-experiments.md`](../docs/operational-experiments.md) once generated from the integrated version.

## Final integrated verification — 2026-10-24

The current working tree re-ran the model and user-facing flow after the warm-reserve, unscheduled-baseline, report UI, and compact-scroll integration. The default API response still produced 1,440 replay frames and 2,109 requests. For the forecast controller versus the all-on FIFO/ASAP baseline, observed facility electricity was 3,079.579 → 2,890.767 kWh (6.131% lower), grid imports 2,567.579 → 2,378.767 kWh (7.354% lower), illustrative cost 1,508.613 → 1,380.123 CNY (8.517% lower), and grid emissions 1,412.169 → 1,308.322 kg (7.354% lower). Service terminal outcomes and accepted flexible work matched; waits and completion latency remain distinct and visible. These are synthetic estimates, not measured savings or tariff validation.

- Full repository suite: `\.venv\Scripts\python.exe -m pytest -q` — **44 passed**.
- `npm run build` — passed, Vite 8.3.5, 27 modules; `git diff --check` — passed.
- `\.venv\Scripts\python.exe tools/operational_experiments.py --seeds 2026 --scenarios normal_day demand_burst constrained_fleet --output-dir results\operational-experiments\seed-2026` — **12 controller rows, 0 failed**, covering four strategies in each of three scenarios; report and CSV are checked in.
- Playwright with installed Microsoft Edge against the source Flask server: dynamic POST returned HTTP 200; policy switching, seeking to 23:59, four baseline-comparison cards and ten service rows worked; at 1366×768 the main graph/replay panels have a bounded 460 px height with keyboard scrolling; at 390×844 the panels stack without page-level horizontal overflow. No page or console errors.
- The Windows onedir build was rebuilt using `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1`. Its ZIP was extracted to `C:\Users\ethna\AppData\Local\Temp\GridShift package final 20261024\GridShift-Windows-x64-onedir` and the bundled `GridShift.exe` was launched from that source-independent path with spaces. The packaged hourly `/api/schedule` and dynamic `/api/dynamic-simulation` flows returned HTTP 200/Optimal; the UI showed 1,440 frames, 2,109 requests, 3,060 flexible GPU-hours, six deadlines, all four comparison cards, and shared seek/cost updates. Desktop was 1366×768; mobile document/body width was 390 px. There were no browser/page errors, and closing the native window stopped the process.

The latest packaged files, rebuilt after the bounded-scroll and keyboard-access adjustment, are `releases/GridShift-Windows-x64-onedir/GridShift.exe` (11,009,812 bytes; SHA-256 `B98E358B9F6FE182059624512A064593EE30CE18017156140D9B37298B600ECB`) and `releases/GridShift-Windows-x64-onedir.zip` (56,562,081 bytes; SHA-256 `ABA55F21359DFF648A2960F78D5E15C2951452DA7E7F2BFCBC80F61EB740CB2F`). At 1366×768 the graph and replay panels share a bounded 460 px workspace; the traffic pane supports keyboard scrolling, and the page requires about 113 px vertical scroll to see the full workspace. This is host-based package evidence, not a clean-VM or signed-executable test. Pricing remains an illustrative October 2026 Fujian agent-purchase proxy, not a verified rate for a particular Xiamen account; power/workload and forecast-margin parameters remain uncalibrated.

Reproduce the default 32×8 run with:

```powershell
.\.venv\Scripts\python.exe -c "from backend.dynamic_simulation import run_dynamic_comparison; r=run_dynamic_comparison({'seed':2026,'nodes':32,'gpus_per_node':8}); print({k:v['metrics'] for k,v in r['policies'].items()}); print(r['comparisons'])"
```
