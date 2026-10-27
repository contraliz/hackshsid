# Forecast backtest: legacy oracle model vs ForecasterV2

Same realistic traffic trace and same controller policy; only the forecast
engine differs. `forecast` reads hidden durations, running end minutes and
the LP hourly rate vector. `forecast_v2` receives none of those.

Metrics are GPU-level: predicted total demand vs realised offered + flexible
demand at the stated horizon. Coverage is the share of realised demand below
the forecast's upper bound (target 0.90).

## Seed 2026 (1721 requests, peak offered 485 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +7.0 | 40.6 | 66.8 | 96.2 | 0.94 | 75.9 |
| 5 | forecast_v2 | -2.3 | 19.0 | 34.8 | 52.0 | 0.90 | 41.3 |
| 10 | forecast | +14.2 | 41.2 | 67.0 | 107.5 | 0.91 | 75.6 |
| 10 | forecast_v2 | -1.9 | 21.2 | 35.4 | 58.0 | 0.90 | 48.1 |
| 15 | forecast | +20.6 | 43.6 | 69.1 | 119.6 | 0.88 | 75.4 |
| 15 | forecast_v2 | -1.4 | 23.8 | 38.0 | 59.9 | 0.88 | 53.5 |
| 20 | forecast | +27.3 | 47.0 | 74.4 | 128.5 | 0.86 | 75.1 |
| 20 | forecast_v2 | -0.4 | 25.4 | 40.5 | 69.0 | 0.90 | 56.3 |
| 30 | forecast | +39.6 | 54.0 | 83.4 | 152.3 | 0.81 | 74.6 |
| 30 | forecast_v2 | +2.8 | 28.6 | 44.5 | 68.2 | 0.88 | 60.6 |
| 40 | forecast | +49.6 | 62.5 | 94.4 | 167.8 | 0.74 | 74.0 |
| 40 | forecast_v2 | +5.7 | 30.7 | 46.0 | 69.3 | 0.88 | 62.7 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 262 | 33.0 | 0 | 0.0 | 6 | 3887.2 |
| reactive | 273 | 34.0 | 0 | 25.4 | 5 | 3825.5 |
| forecast | 262 | 33.0 | 0 | 71.6 | 5 | 3808.9 |
| forecast_v2 | 262 | 33.0 | 0 | 70.5 | 5 | 3814.9 |

## Seed 2028 (2281 requests, peak offered 437 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | -6.8 | 52.4 | 74.1 | 131.8 | 0.98 | 126.1 |
| 5 | forecast_v2 | -2.7 | 19.9 | 36.8 | 71.0 | 0.93 | 87.7 |
| 10 | forecast | +1.2 | 53.6 | 75.7 | 135.6 | 0.95 | 125.8 |
| 10 | forecast_v2 | -4.6 | 21.5 | 37.8 | 69.0 | 0.95 | 88.0 |
| 15 | forecast | +8.0 | 54.9 | 78.0 | 142.5 | 0.94 | 125.6 |
| 15 | forecast_v2 | -5.8 | 23.5 | 42.2 | 72.9 | 0.95 | 90.4 |
| 20 | forecast | +14.3 | 56.1 | 81.7 | 150.0 | 0.93 | 125.3 |
| 20 | forecast_v2 | -6.0 | 25.4 | 43.9 | 80.4 | 0.94 | 92.4 |
| 30 | forecast | +29.8 | 59.2 | 88.4 | 167.5 | 0.88 | 124.8 |
| 30 | forecast_v2 | -3.8 | 27.3 | 44.7 | 80.0 | 0.94 | 96.7 |
| 40 | forecast | +42.9 | 65.5 | 96.9 | 175.5 | 0.84 | 124.3 |
| 40 | forecast_v2 | -2.7 | 27.9 | 45.4 | 84.0 | 0.93 | 98.0 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 426 | 34.0 | 0 | 382.9 | 4 | 3965.1 |
| reactive | 426 | 34.0 | 0 | 392.1 | 4 | 3916.5 |
| forecast | 426 | 34.0 | 0 | 405.9 | 4 | 3922.0 |
| forecast_v2 | 426 | 34.0 | 0 | 405.6 | 4 | 3932.2 |

## Seed 7 (2078 requests, peak offered 435 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | -10.6 | 66.6 | 91.7 | 152.2 | 0.95 | 115.9 |
| 5 | forecast_v2 | -2.6 | 21.3 | 38.4 | 60.0 | 0.91 | 86.9 |
| 10 | forecast | -1.0 | 66.4 | 88.3 | 147.1 | 0.93 | 115.7 |
| 10 | forecast_v2 | -3.1 | 24.4 | 40.6 | 61.0 | 0.89 | 93.6 |
| 15 | forecast | +6.8 | 65.9 | 86.3 | 147.4 | 0.93 | 115.5 |
| 15 | forecast_v2 | -3.4 | 26.4 | 42.4 | 66.8 | 0.90 | 97.5 |
| 20 | forecast | +14.3 | 65.1 | 85.9 | 149.7 | 0.92 | 115.3 |
| 20 | forecast_v2 | -3.2 | 27.5 | 43.4 | 67.2 | 0.90 | 105.1 |
| 30 | forecast | +29.1 | 67.3 | 89.2 | 157.2 | 0.90 | 114.9 |
| 30 | forecast_v2 | -1.8 | 28.7 | 43.8 | 65.0 | 0.90 | 110.8 |
| 40 | forecast | +42.2 | 68.4 | 92.8 | 166.1 | 0.87 | 114.5 |
| 40 | forecast_v2 | -0.3 | 29.5 | 44.2 | 66.3 | 0.91 | 112.8 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 484 | 37.0 | 0 | 506.0 | 4 | 3949.6 |
| reactive | 484 | 37.0 | 0 | 520.5 | 4 | 3897.6 |
| forecast | 484 | 37.0 | 0 | 545.0 | 4 | 3898.8 |
| forecast_v2 | 484 | 37.0 | 0 | 541.7 | 4 | 3909.9 |
