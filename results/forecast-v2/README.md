# Forecasting v2: draft replacement for the oracle-fed forecaster

This folder is the evidence bundle for the `gridshift-forecast/` clone. It
answers two questions: what the new forecaster is allowed to know, and whether
it predicts better than the one it replaces.

## What changed

1. **New traffic generator** (`backend/traffic_realistic.py`) replaces the
   uniform-Poisson demo as the default. It uses heavy-tailed sizes and
   durations, two AR(1) intensity processes (bursts plus slow regime shifts),
   a gang-job tail and a class mix that shifts across the day. Default demo is
   now 40 nodes × 8 GPUs, seed 2026, realistic shape.
2. **`forecast_v2`** (`backend/forecast_v2.py`) is a fourth controller next to
   the legacy `forecast`. The UI now exposes only v2; the legacy engine stays in
   the API as the comparison baseline for the backtest. It is given only observable inputs; the adapter
   `_forecast_v2_curve` in `backend/dynamic_simulation.py` deliberately passes
   `(class, gpus, age)` for running jobs and `(class, gpus, arrival)` for
   queued jobs — no durations, no end minutes, no LP hourly rates.
3. **Backtest harness** (`scripts/benchmark_forecast.py`) that scores both
   engines against realised demand at horizons 5–40 minutes.

## Why the legacy forecaster scored badly here

It is not that the oracle model is badly written; it is mis-specified for the
new trace. It seeds its arrival EWMA from the *old* generator's rates, rescales
by `tod(h)/tod(t)`, and reads exact durations and the LP rate vector. On the
heavier-tailed trace its bias grows from +8 GPUs at 5 minutes to +36 GPUs at 40
minutes, and it holds a ~74 GPU upper margin. That is a correct forecast for
the old demo, not a transferable one.

## Headline numbers (seed 2026, horizon 5 min)

| engine | bias | MAE | RMSE | mean upper margin | coverage |
|---|---:|---:|---:|---:|---:|
| forecast (oracle inputs) | +7.9 | 48.6 | 72.2 | 74.6 | 0.90 |
| forecast_v2 (observable only) | −5.3 | 11.7 | 18.6 | 8.9 | 0.89 |

Full tables for seeds 2026, 2028 and 7 are in `backtest.md` / `backtest.json`.

## Anti-churn controls (added after review)

The first draft converted forecast noise into power cycling: a node would boot
for a predicted peak, sit warm, be powered off after 30 idle minutes, and be
booted again for the next prediction. In the 40-node demo, 97% of boots were
these "activation" boots and 100 boot→warm→off cycles never reached active.

Three gates now apply:

| gate | value | purpose |
|---|---:|---|
| deadband | 2 nodes | ignore gaps a single node wide |
| confirmation | 2 issues (10 min) | require the gap to persist |
| cooldown | 30 min | never re-boot a just-powered-off node |

Result on seed 2026: boot node-minutes 3,020 → 1,700, never-active cycles
100 → 43, facility kWh 3,679 → 3,631, waits unchanged at 0.

## Savings tab: queue and wait

The savings report now carries a visible "Queue and wait" row comparing the
unscheduled baseline with the selected controller: requests that waited, mean
queue wait, P95 queue wait, and peak queue depth. These come from the minute
replay (`peak_queued_requests` is the maximum queued-request count over the
whole day), so they are observed values, not forecast estimates.

## Honest limitations

* The realistic generator is synthetic. It is shaped to produce queueing and
  heavy tails, not fitted to a production trace.
* `forecast_v2` assumes the flexible dispatcher stays greedy (real-time first,
  then flexible up to `max_gpus`). If that policy changes, the flexible term
  must change with it.
* Queue placement uses an expected duration from the survival curve, not a
  per-job estimate; long queued jobs can be packed too optimistically.
* Conformal coverage lands at 0.86–0.91 against a 0.92 nominal level because
  residuals are autocorrelated; the bound is honest but not exact.
* Service outcomes remain dominated by fleet sizing. When offered demand
  exceeds installed capacity, no forecaster prevents a queue.

## Reproduce

```bash
cd gridshift-forecast
python scripts/benchmark_forecast.py     # writes results/forecast-v2/
python -m pytest tests -q
```
