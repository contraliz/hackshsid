# Issues

## QA-01 — Low severity, resolved and retested

- **Summary:** The node-state chart encodes power state, not occupancy, so a blue active row alone did not tell the user how many GPUs were busy versus immediately free. The user interpreted the interval as having no usable reserve and downtime.
- **Precondition:** Default seed 2026, Normal profile, 32 × 8 nodes, zero extra headroom, Forecast controller.
- **Observed data:** At 01:00, 23 active GPUs were idle and ready; at 01:10, warm standby had drained to zero but 28 active GPUs were idle and ready. All 30 requests arriving from 01:00 through 01:59 started at arrival; day and interval waiting counts were zero. Thus this reproduction showed ambiguous reserve visibility, not service downtime.
- **Expected:** State legend and selected-minute details should separately show occupied active capacity, immediately dispatchable active spare GPUs, five-minute warm standby, warming/booting/off capacity, actual request queue, and forecast-only gaps.
- **Resolution:** Added the explicit selected-minute ready-capacity panel and clearer power-state/forecast-gap descriptions; node details identify idle active GPUs and warm activation time.
- **Retest:** QA run `run-mvp7o7sm-2a25a6`, desktop 1366 × 768. See [01:10 retest capture](captures/minute-0110-zero-warm-active-spare.png), [01:00](captures/minute-0100-ready-active-vs-warm.png), and [02:00](captures/minute-0200-flexible-shift.png). The panel showed 28 idle active GPUs at 01:10, zero warm, and zero waiting.
- **Evidence:** `measurements.json` (no overflow/runtime events), `steps.json`, `results/ready-reserve-01-02-baseline-2026.json`, and `results/ready-reserve-01-02-after-2026.json`.

Measurement-only flags: five small targets and one clipped compact description were observed; neither blocked the tested controls nor obscured queue or reserve values, so they are not tracked as product defects.
