# Immediate-warm policy: same-input comparison (2026-10-26)

Captured 2026-10-26T13:27:53.231646+00:00. These are same-seed, same-request-trace comparisons against the pre-change saved baseline. The revised scenario uses 0-minute warm promotion and a default two-node warm-stock target; cold boot remains 20 minutes.

| Case | Controller | Waited requests (before → after) | Mean / p95 wait min (before → after) | Flexible GPU·h delivered (before → after) | Flex deadline misses (before → after) | Facility kWh (before → after) | Grid cost CNY (before → after) | Warm-ready zero minutes (before → after) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| normal_default | always_on | 0 → 0 | 0.0 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 3091.8 → 3091.8 | 1518.927 → 1518.878 | 739 → 1440 |
| normal_default | reactive | 10 → 10 | 0.01 / 0 → 0.01 / 0 | 3060.0 → 3060.0 | 0 → 0 | 2897.232 → 2892.972 | 1384.728 → 1382.154 | 739 → 1200 |
| normal_default | forecast | 0 → 0 | 0.0 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 2927.217 → 2906.758 | 1401.48 → 1394.018 | 739 → 0 |
| low_default | always_on | 0 → 0 | 0.0 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 2962.504 → 2962.504 | 1427.803 → 1425.427 | 715 → 1440 |
| low_default | reactive | 0 → 0 | 0.0 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 2761.093 → 2753.186 | 1288.307 → 1279.897 | 715 → 1209 |
| low_default | forecast | 0 → 0 | 0.0 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 2783.848 → 2749.884 | 1300.456 → 1280.465 | 715 → 0 |
| high_default | always_on | 79 → 5 | 0.04 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 3359.63 → 3360.024 | 1709.612 → 1715.56 | 871 → 1440 |
| high_default | reactive | 117 → 12 | 0.06 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 3206.193 → 3216.732 | 1608.944 → 1624.468 | 871 → 1205 |
| high_default | forecast | 89 → 11 | 0.04 / 0 → 0.0 / 0 | 3060.0 → 3060.0 | 0 → 0 | 3257.87 → 3240.925 | 1640.261 → 1640.202 | 871 → 19 |
| constrained_high | always_on | 801 → 801 | 2.73 / 20 → 2.73 / 20 | 0.0 → 0.0 | 0 → 0 | 1421.274 → 1421.274 | 588.73 → 588.73 | 781 → 1440 |
| constrained_high | reactive | 904 → 886 | 3.46 / 27 → 3.33 / 26 | 0.0 → 0.0 | 0 → 0 | 1329.292 → 1328.557 | 552.744 → 552.452 | 781 → 1239 |
| constrained_high | forecast | 802 → 801 | 2.73 / 20 → 2.73 / 20 | 0.0 → 0.0 | 0 → 0 | 1366.769 → 1361.639 | 567.106 → 564.655 | 781 → 332 |

## Trace and window notes

- **normal_default**: 2109 requests, trace SHA-256 `3a7b1ccb10e97361338b1b163c1a3ef223b597394fc2c0f5afd4ca3d626d9d30`, offered peak 109 GPUs. Forecast warm-ready zero minutes: 739 → 0; minimum active spare in 01:00–02:00: 22.0 → 22.0 GPUs. At 01:10: {'active_nodes': 15, 'warm_ready_nodes': 2, 'booting_nodes': 0, 'off_nodes': 15, 'active_spare_gpus': 28.0, 'dispatchable_capacity_gpus': 44.0, 'queued_requests': None} .
- **low_default**: 989 requests, trace SHA-256 `ffa406a40a0ba02f41f5fc779c35c3457c2854c8c74203eb2356a35a57d2a2e6`, offered peak 51 GPUs. Forecast warm-ready zero minutes: 715 → 0; minimum active spare in 01:00–02:00: 28.0 → 28.0 GPUs. At 01:10: {'active_nodes': 15, 'warm_ready_nodes': 2, 'booting_nodes': 0, 'off_nodes': 15, 'active_spare_gpus': 28.0, 'dispatchable_capacity_gpus': 44.0, 'queued_requests': None} .
- **high_default**: 4052 requests, trace SHA-256 `454fb128f108940ddfe7ba9a77e7004d3d8a541f151e66ae047b95d36cc5186f`, offered peak 267 GPUs. Forecast warm-ready zero minutes: 871 → 19; minimum active spare in 01:00–02:00: 15.0 → 6.0 GPUs. At 01:10: {'active_nodes': 15, 'warm_ready_nodes': 2, 'booting_nodes': 0, 'off_nodes': 15, 'active_spare_gpus': 23.0, 'dispatchable_capacity_gpus': 39.0, 'queued_requests': None} .
- **constrained_high**: 4052 requests, trace SHA-256 `454fb128f108940ddfe7ba9a77e7004d3d8a541f151e66ae047b95d36cc5186f`, offered peak 267 GPUs. Forecast warm-ready zero minutes: 781 → 332; minimum active spare in 01:00–02:00: 2.0 → 2.0 GPUs. At 01:10: {'active_nodes': 5, 'warm_ready_nodes': 2, 'booting_nodes': 0, 'off_nodes': 5, 'active_spare_gpus': 23.0, 'dispatchable_capacity_gpus': 39.0, 'queued_requests': None} .

A zero wait/zero flex miss in a specific seeded run is an observation, not a cross-seed guarantee. Warm stock can be depleted during sustained peaks; cold replacement takes 20 minutes. `grid_cost` is an illustrative hourly tariff proxy, not a site bill. Each after-case stores 24 tariff rows per controller in the JSON artifact.

Machine-readable rows: [instant-warm-policy-comparison-2026.json](instant-warm-policy-comparison-2026.json).
