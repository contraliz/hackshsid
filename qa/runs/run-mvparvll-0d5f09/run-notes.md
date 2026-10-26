# Desktop QA run notes

- Outcome: **Pass for the inspected desktop flow**.
- App: GridShift at `http://127.0.0.1:8001/`.
- Run: `run-mvparvll-0d5f09` on 2026-10-26, viewport 1366 × 768.
- Intent: inspect the default desktop simulation, Forecast replay at 01:10, full-width node-state timeline, node work labels, immediate warm standby counters, and hourly grid-cost table.
- Acceptance checks: page loads; the default simulation runs; replay can seek to 01:10; warm standby is shown as ready now; timeline uses the main panel width; node details retain workload labels; hourly tariff table is readable.

## Coverage and result

All 19 recorded actions succeeded. The page reported the default 32-node, 8-GPU-per-node, Normal-traffic scenario with two warm standby nodes. At 01:10 the screenshot shows 15 active nodes, 2 warm-ready nodes (16 GPUs), and 44 GPUs of ready-now capacity including 28 idle active GPUs. The observed queue was empty. The cost table shows a daily illustrative grid cost of ¥1,394.02, with hourly local-time rows.

The inspected desktop screenshots show the node timeline spanning the main panel and the tariff rows rendered in the table. The measurement bundle reports no horizontal overflow, broken images, missing image alt text, or clipped text. It reports five small-target matches; these include a 13×13 checkbox and a 16px-high range input, so the aggregate count is recorded without classifying every match as a confirmed defect. No runtime errors were recorded.

Mobile coverage was explicitly excluded by the user and was not performed in this run. This run does not establish behavior outside the stated desktop viewport or prove production tariff accuracy.

## Evidence

- [Initial desktop view](captures/initial-default.png)
- [Default warm-stock controls](captures/controls-default-two-warm-nodes.png)
- [01:10 forecast state](captures/forecast-readiness-0110.png)
- [Full-width node-state timeline](captures/full-width-node-state-timeline.png)
- [Node work labels and ready cards](captures/0110-node-work-labels-and-ready-cards.png)
- [Hourly grid-cost table](captures/hourly-grid-cost-table.png)
- [Recorded steps](steps.json)
- [Measurements](measurements.json)
- [Issue list](issues.md)
