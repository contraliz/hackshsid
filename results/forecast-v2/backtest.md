# Forecast backtest: legacy oracle model vs ForecasterV2

Same realistic traffic trace and same controller policy; only the forecast
engine differs. `forecast` reads hidden durations, running end minutes and
the LP hourly rate vector. `forecast_v2` receives none of those.

Metrics are GPU-level: predicted total demand vs realised offered + flexible
demand at the stated horizon. Coverage is the share of realised demand below
the forecast's upper bound (target 0.90).

## Seed 2026 (1552 requests, peak offered 282 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +7.9 | 48.6 | 72.2 | 141.1 | 0.90 | 74.6 |
| 5 | forecast_v2 | -5.3 | 11.7 | 18.6 | 25.9 | 0.89 | 8.9 |
| 10 | forecast | +13.9 | 49.3 | 72.7 | 136.2 | 0.88 | 74.4 |
| 10 | forecast_v2 | -6.5 | 15.4 | 22.9 | 40.4 | 0.91 | 15.5 |
| 15 | forecast | +18.4 | 50.6 | 73.8 | 137.6 | 0.86 | 74.3 |
| 15 | forecast_v2 | -7.6 | 17.2 | 24.4 | 44.1 | 0.89 | 19.4 |
| 20 | forecast | +22.2 | 52.2 | 75.8 | 148.1 | 0.86 | 74.2 |
| 20 | forecast_v2 | -8.1 | 18.1 | 25.0 | 44.8 | 0.91 | 22.3 |
| 30 | forecast | +30.6 | 55.8 | 80.5 | 159.2 | 0.82 | 73.8 |
| 30 | forecast_v2 | -7.4 | 21.0 | 29.0 | 52.0 | 0.90 | 32.4 |
| 40 | forecast | +36.7 | 59.6 | 84.9 | 171.2 | 0.79 | 73.5 |
| 40 | forecast_v2 | -7.3 | 22.3 | 30.4 | 52.7 | 0.88 | 34.9 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 6 | 0.0 | 0 | 0.0 | 6 | 3595.8 |
| reactive | 33 | 0.0 | 0 | 0.0 | 6 | 3499.6 |
| forecast | 8 | 0.0 | 0 | 0.0 | 6 | 3535.3 |
| forecast_v2 | 6 | 0.0 | 0 | 0.0 | 6 | 3528.0 |

## Seed 2028 (1957 requests, peak offered 374 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +1.9 | 53.0 | 77.2 | 141.5 | 0.92 | 108.5 |
| 5 | forecast_v2 | -2.0 | 12.1 | 23.1 | 40.0 | 0.92 | 50.4 |
| 10 | forecast | +9.0 | 54.7 | 78.0 | 145.3 | 0.91 | 108.4 |
| 10 | forecast_v2 | -3.5 | 14.1 | 25.7 | 45.0 | 0.94 | 52.3 |
| 15 | forecast | +15.9 | 56.8 | 80.2 | 142.3 | 0.87 | 108.4 |
| 15 | forecast_v2 | -4.7 | 15.8 | 29.2 | 47.6 | 0.94 | 48.8 |
| 20 | forecast | +22.9 | 59.2 | 83.1 | 148.8 | 0.84 | 108.3 |
| 20 | forecast_v2 | -5.5 | 17.1 | 31.2 | 52.0 | 0.93 | 47.8 |
| 30 | forecast | +35.4 | 66.5 | 91.9 | 162.5 | 0.76 | 108.1 |
| 30 | forecast_v2 | -6.0 | 18.5 | 34.6 | 62.0 | 0.93 | 53.1 |
| 40 | forecast | +44.8 | 71.7 | 99.1 | 178.4 | 0.70 | 108.0 |
| 40 | forecast_v2 | -6.1 | 19.7 | 37.1 | 66.0 | 0.92 | 58.7 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 176 | 9.0 | 0 | 206.8 | 5 | 3959.7 |
| reactive | 176 | 9.0 | 0 | 211.2 | 5 | 3927.8 |
| forecast | 176 | 9.0 | 0 | 219.6 | 5 | 3931.3 |
| forecast_v2 | 176 | 9.0 | 0 | 219.0 | 5 | 3940.9 |

## Seed 7 (2148 requests, peak offered 428 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +3.3 | 70.2 | 92.3 | 154.1 | 0.95 | 133.8 |
| 5 | forecast_v2 | -1.8 | 14.1 | 30.5 | 45.0 | 0.91 | 50.0 |
| 10 | forecast | +11.9 | 69.5 | 92.2 | 158.7 | 0.93 | 133.7 |
| 10 | forecast_v2 | -2.6 | 16.4 | 32.2 | 54.6 | 0.89 | 54.7 |
| 15 | forecast | +18.6 | 69.1 | 93.2 | 163.6 | 0.90 | 133.7 |
| 15 | forecast_v2 | -3.3 | 16.8 | 33.2 | 53.3 | 0.90 | 56.9 |
| 20 | forecast | +25.4 | 69.3 | 94.9 | 169.2 | 0.87 | 133.6 |
| 20 | forecast_v2 | -3.7 | 17.8 | 33.3 | 52.0 | 0.90 | 57.3 |
| 30 | forecast | +38.4 | 70.8 | 98.2 | 182.8 | 0.80 | 133.4 |
| 30 | forecast_v2 | -3.1 | 19.4 | 34.7 | 56.0 | 0.89 | 59.4 |
| 40 | forecast | +48.4 | 73.5 | 102.0 | 189.6 | 0.74 | 133.2 |
| 40 | forecast_v2 | -2.2 | 20.6 | 37.2 | 60.3 | 0.90 | 63.3 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 186 | 12.0 | 0 | 188.6 | 5 | 3933.7 |
| reactive | 186 | 12.0 | 0 | 191.6 | 5 | 3889.6 |
| forecast | 186 | 12.0 | 0 | 196.7 | 5 | 3895.5 |
| forecast_v2 | 186 | 12.0 | 0 | 203.9 | 5 | 3889.3 |
