# Issues

## QA-01 — Medium severity, resolved and retested

- **Symptom:** The node power timeline was not visible in the initial State timeline panel. Reserve cards and diagnostics occupied the compact panel first, and the SVG timeline collapsed rather than displaying its rows.
- **Impact:** The main per-node history was difficult to discover and appeared absent.
- **Preconditions:** Operations page, default seed 2026, Normal traffic, 32 nodes × 8 GPUs, zero headroom, Forecast controller.
- **Steps:** Run the simulation; inspect the initially selected State timeline tab.
- **Expected:** The colored full-day, per-node chart is visible directly under its legend in the main panel; reserve details follow it.
- **Actual before fix:** The chart was missing from the initial panel view. Evidence: [baseline capture](../run-mvp81kyi-58a6be/captures/before-compact-node-panel.png).
- **Resolution:** Restored the timeline to the first content position under its legend, set explicit chart dimensions so SVG content renders, and moved Node details to the start of its tab.
- **Retest:** [desktop default timeline](captures/state-timeline-default-visible.png), [01:10 replay](captures/state-timeline-0110-reserve-context.png), and [node workload labels](captures/node-details-work-labels.png). At 390 × 844, the [mobile timeline](../run-mvp8et31-b0c0ae/captures/mobile-state-timeline-visible.png) also rendered with zero horizontal page overflow.
- **Affected view:** `/`, Operations → Node power states → State timeline; desktop and mobile compact dashboard.
