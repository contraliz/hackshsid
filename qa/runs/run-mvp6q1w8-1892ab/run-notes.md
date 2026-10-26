# QA run notes

- **Application:** GridShift, `http://127.0.0.1:8001/`
- **Run ID:** `run-mvp6q1w8-1892ab`
- **Date:** 2026-10-26
- **Viewport:** 1366 × 768
- **Outcome:** pass for the exercised desktop flow; no confirmed product defects.

## Intent and acceptance

Exercise the data-center operations initial controls and a High-traffic ample-fleet run. Confirm the fixed headroom and warm-overhead controls work, replay renders, the slider seeks to the measured 19:03 demand peak, and controller selection can be changed. Review layout/runtime measurements for overflow or errors.

## Flow exercised

1. Opened the app and waited for “Data center operations”; inspected default controls (seed 2026, Normal 1×, Standard inventory).
2. Set 48 base nodes, High 2× traffic, 16 fixed headroom nodes, 1 warm overhead node, 50% minimum-active floor, and turned off the seeded burst; ran the simulation.
3. Observed 3,913 generated requests and the displayed actual offered-load peak at 19:03 (127 GPUs). Because this QA run used a 50% minimum-active floor, its peak snapshot showed 32 active, 1 warm-ready, 0 booting, 0 warming, and 31 off. This differs from the comparable metrics fixture, which uses the default floor and is documented separately.
4. Sought to 19:03, switched to Reactive and back to Forecast, opened the assumptions, and inspected captures.

## Evidence

- [Initial controls](captures/initial-controls.png)
- [High ample result and summary](captures/high-ample-result.png)
- [19:03 replay seek](captures/peak-node-state.png)
- [Reactive controller comparison](captures/reactive-controller.png)
- [Wait-aware assumptions view](captures/forecast-equations-and-assumptions.png)
- [Measurements](measurements.json)
- [Executed steps](steps.json)

The inspected screenshots show the desktop controls, generated result, demand peak, and both policy selection states. The assumptions capture includes the displayed causal EWMA/duration-survival explanation and the margin caveat. A few compact descriptive labels are ellipsized by the existing card layout; that does not hide the measured results or the active controls.

## Measurement and coverage

- Horizontal overflow: 0; broken images: 0; missing image alt: 0; runtime events: 0.
- The small-target rule flagged compact links, the checkbox, and the slider; the clipped-text rule flagged an intentionally single-line live-replay description. These were measurement signals, not confirmed defects.
- This run did not test the mobile layout, long-run behavior, or an external production trace.
