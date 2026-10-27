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
| 5 | forecast | +7.8 | 49.6 | 73.0 | 141.1 | 0.89 | 74.6 |
| 5 | forecast_v2 | -5.6 | 11.5 | 17.1 | 25.7 | 0.89 | 8.7 |
| 10 | forecast | +13.8 | 50.3 | 73.4 | 136.2 | 0.88 | 74.4 |
| 10 | forecast_v2 | -6.9 | 14.2 | 19.8 | 35.4 | 0.90 | 14.1 |
| 15 | forecast | +18.3 | 51.5 | 74.5 | 137.6 | 0.86 | 74.3 |
| 15 | forecast_v2 | -8.0 | 15.6 | 21.2 | 36.3 | 0.90 | 17.2 |
| 20 | forecast | +22.1 | 53.1 | 76.5 | 148.1 | 0.86 | 74.2 |
| 20 | forecast_v2 | -8.6 | 17.0 | 22.8 | 36.0 | 0.91 | 20.3 |
| 30 | forecast | +30.5 | 56.7 | 81.2 | 159.2 | 0.82 | 73.8 |
| 30 | forecast_v2 | -7.9 | 19.2 | 25.7 | 46.7 | 0.90 | 25.6 |
| 40 | forecast | +36.6 | 60.5 | 85.5 | 171.2 | 0.79 | 73.5 |
| 40 | forecast_v2 | -7.8 | 20.4 | 27.1 | 47.5 | 0.89 | 28.4 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 6 | 0.0 | 0 | 0.0 | 6 | 3595.8 |
| reactive | 33 | 0.0 | 0 | 0.0 | 6 | 3499.6 |
| forecast | 11 | 0.0 | 0 | 0.0 | 6 | 3529.2 |
| forecast_v2 | 6 | 0.0 | 0 | 0.0 | 6 | 3516.4 |

## Seed 2028 (1957 requests, peak offered 374 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +2.0 | 53.2 | 77.4 | 141.5 | 0.92 | 108.7 |
| 5 | forecast_v2 | -1.9 | 11.9 | 22.8 | 40.0 | 0.91 | 50.0 |
| 10 | forecast | +9.1 | 55.0 | 78.2 | 145.3 | 0.91 | 108.6 |
| 10 | forecast_v2 | -3.5 | 13.8 | 25.3 | 44.6 | 0.94 | 52.0 |
| 15 | forecast | +15.9 | 57.0 | 80.4 | 142.3 | 0.87 | 108.5 |
| 15 | forecast_v2 | -4.7 | 15.6 | 28.9 | 47.2 | 0.94 | 48.5 |
| 20 | forecast | +22.9 | 59.4 | 83.4 | 148.8 | 0.84 | 108.5 |
| 20 | forecast_v2 | -5.4 | 16.8 | 31.0 | 52.0 | 0.94 | 47.4 |
| 30 | forecast | +35.4 | 66.7 | 92.1 | 162.5 | 0.76 | 108.3 |
| 30 | forecast_v2 | -5.9 | 18.4 | 34.6 | 62.0 | 0.93 | 52.8 |
| 40 | forecast | +44.9 | 71.9 | 99.3 | 178.4 | 0.69 | 108.1 |
| 40 | forecast_v2 | -5.9 | 19.5 | 37.2 | 65.0 | 0.91 | 58.0 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 176 | 9.0 | 0 | 206.8 | 5 | 3959.7 |
| reactive | 176 | 9.0 | 0 | 211.2 | 5 | 3927.8 |
| forecast | 176 | 9.0 | 0 | 219.8 | 5 | 3929.1 |
| forecast_v2 | 176 | 9.0 | 0 | 220.8 | 5 | 3935.1 |

## Seed 7 (2148 requests, peak offered 428 GPUs, fleet 256)

| horizon | engine | bias | MAE | RMSE | p90 abs | coverage | upper width |
|---:|---|---:|---:|---:|---:|---:|---:|
| 5 | forecast | +3.3 | 70.2 | 92.1 | 154.1 | 0.95 | 133.8 |
| 5 | forecast_v2 | -1.8 | 14.1 | 30.5 | 45.0 | 0.90 | 49.7 |
| 10 | forecast | +12.0 | 69.4 | 92.1 | 158.7 | 0.93 | 133.7 |
| 10 | forecast_v2 | -2.6 | 16.0 | 31.6 | 52.0 | 0.89 | 54.0 |
| 15 | forecast | +18.6 | 69.0 | 93.0 | 163.6 | 0.90 | 133.7 |
| 15 | forecast_v2 | -3.3 | 16.4 | 32.4 | 52.6 | 0.90 | 56.2 |
| 20 | forecast | +25.4 | 69.0 | 94.6 | 169.2 | 0.87 | 133.6 |
| 20 | forecast_v2 | -3.5 | 17.4 | 32.7 | 51.7 | 0.90 | 57.1 |
| 30 | forecast | +38.4 | 70.6 | 98.1 | 182.8 | 0.80 | 133.4 |
| 30 | forecast_v2 | -3.0 | 19.1 | 34.3 | 55.0 | 0.90 | 59.7 |
| 40 | forecast | +48.4 | 73.2 | 101.8 | 189.6 | 0.74 | 133.2 |
| 40 | forecast_v2 | -2.0 | 20.2 | 36.4 | 59.0 | 0.90 | 61.4 |

| controller | waited | p95 wait | rejected | flex unmet GPU·h | deadlines | facility kWh |
|---|---:|---:|---:|---:|---:|---:|
| always_on | 186 | 12.0 | 0 | 188.6 | 5 | 3933.7 |
| reactive | 186 | 12.0 | 0 | 191.6 | 5 | 3889.6 |
| forecast | 186 | 12.0 | 0 | 196.7 | 5 | 3893.4 |
| forecast_v2 | 186 | 12.0 | 0 | 206.7 | 5 | 3882.6 |
