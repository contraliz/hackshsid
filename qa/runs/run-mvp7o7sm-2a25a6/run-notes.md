# QA run notes

- **Application:** GridShift, `http://127.0.0.1:8001/`
- **Run ID:** `run-mvp7o7sm-2a25a6`
- **Date:** 2026-10-26
- **Viewport:** 1366 × 768
- **Outcome:** pass for the default Forecast interval flow after the reserve-visibility correction; one low-severity chart-interpretation issue was resolved and retested.

## Intent and acceptance

Reproduce the user's default configuration with Forecast selected and zero added headroom. Seek 01:00, 01:10, 01:15, and 02:00. Verify the UI distinguishes active idle GPUs available now from occupied active GPUs, warm standby, nodes still starting, actual queue, and forecast-only readiness gaps. Confirm the deterministic request trace is unchanged.

## Flow exercised

1. Opened the local app; confirmed defaults 32 nodes × 8 GPUs, seed 2026, Normal 1×, Standard inventory (0 headroom). Opened More controls and confirmed EWMA alpha 0.3, fallback margin 0.15, floor 4 GPUs, minimum-active floor 0.25, warm overhead 1, and seeded burst chance on.
2. Ran simulation and selected Forecast; it returned 2,109 generated requests.
3. Sought to minute 60 (01:00): 120 active GPUs, 97 occupied (17 realtime + 80 flexible), 23 idle active GPUs ready now, 1 warm node (8 GPUs, 5-minute activation), 16 off, no waiting.
4. Sought to minute 70 (01:10): 120 active GPUs, 92 occupied (12 realtime + 80 flexible), 28 idle active GPUs ready now, zero warm, 1 warming, 12 booting, 4 off, no waiting. This shows standby can be depleted while immediate active spare remains; the forecast-only fractional readiness gap is not observed waiting.
5. Sought minute 75 (01:15): 120 active GPUs, 88 occupied (8 realtime + 80 flexible), 32 idle active GPUs ready now, 1 warm node, no waiting.
6. Sought minute 120 (02:00): 216 active GPUs, 180 occupied (10 realtime + 170 flexible), 36 idle active GPUs, 1 warm node, 1 booting, 3 off, no waiting. Opened Node details to inspect per-node workload labels and idle counts.

## Evidence

- Initial defaults: [initial-default-controls.png](captures/initial-default-controls.png)
- All default reserve controls: [default-reserve-settings.png](captures/default-reserve-settings.png)
- 01:00 ready active vs warm: [minute-0100-ready-active-vs-warm.png](captures/minute-0100-ready-active-vs-warm.png)
- 01:10 zero warm but active spare: [minute-0110-zero-warm-active-spare.png](captures/minute-0110-zero-warm-active-spare.png)
- 01:15 warm standby restored: [minute-0115-warm-restored.png](captures/minute-0115-warm-restored.png)
- 02:00 workload and ready capacity: [minute-0200-flexible-shift.png](captures/minute-0200-flexible-shift.png)
- 02:00 node detail: [minute-0200-per-node-ready-vs-used.png](captures/minute-0200-per-node-ready-vs-used.png)
- QA measurements and actions: [measurements.json](measurements.json), [steps.json](steps.json)
- Same-trace before/after facts and full-day metrics: [baseline JSON](../../../results/ready-reserve-01-02-baseline-2026.json), [after JSON](../../../results/ready-reserve-01-02-after-2026.json)
- Issue classification and retest: [issues.md](issues.md)

The named captures were opened and visually inspected. The 01:10 screenshot visibly distinguishes idle active GPUs from warm standby and actual queue. Deterministic trace SHA-256 is identical before and after (`d64714f39e6fd3cfe4289ac7fd722eb6cdfe7a4a6060bfd8c2bd097fc6357aa8`). Backend/policy behavior did not change in this UI correction; day energy and delivered work are identical.

## Measurements and limits

- Horizontal overflow: 0; broken images: 0; missing image alt: 0; runtime events: 0.
- Small targets: 5 (logo, checkbox, slider, and two source links); the tested controls worked. One compact live-traffic description was clipped, but the queue count remained visible.
- Desktop viewport only; mobile coverage was not run.
- This is a deterministic synthetic seed, not a live hardware trace. No requests waited in this hour or on the day. Warm standby was zero at minutes 70–74, but active idle capacity stayed positive; a forecast readiness gap must not be described as downtime.
