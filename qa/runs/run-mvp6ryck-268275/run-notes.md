# QA run notes

- **Application:** GridShift, `http://127.0.0.1:8001/`
- **Run ID:** `run-mvp6ryck-268275`
- **Date:** 2026-10-26
- **Viewport:** 390 × 844
- **Outcome:** pass for the exercised mobile control and constrained-load flow; no confirmed product defects.

## Intent and acceptance

Check that the primary controls remain usable on a narrow viewport, High traffic and adjustable warm overhead can be selected, the constrained burst replay is rendered, and the selected-minute node view remains in bounds.

## Flow exercised

1. Opened the app and captured the default mobile controls.
2. Set 12 nodes × 8 GPUs, High 2× traffic, two warm-overhead nodes, and kept the seeded burst enabled.
3. Ran the simulation and observed 4,052 generated requests, a 267-GPU offered peak against 96 installed GPUs, and the displayed readiness/fleet gap.
4. Sought to 17:24 and switched Node power states to Node details.

## Evidence

- [Mobile initial controls](captures/mobile-initial-controls.png)
- [Constrained high-traffic result and gap](captures/mobile-constrained-results.png)
- [17:24 node/readiness view](captures/mobile-peak-readiness-and-work.png)
- [Measurements](measurements.json)
- [Executed steps](steps.json)

The inspected mobile captures show no horizontal page overflow. The result cards and settings stack vertically; the constrained result exposes the fleet and readiness problem instead of implying full coverage. Some compact card copy is ellipsized while the metric values remain visible.

## Measurement and coverage

- Document scroll width equaled viewport width (390 px); broken images: 0; missing image alt: 0; runtime events: 0.
- The clipped-text rule flagged the “Illustrative grid cost” card label and two descriptive/summary labels. The primary numeric values remained visible; labels are intentionally truncated by compact styles and were not judged a functional defect.
- The small-target rule flagged compact links, checkbox, slider, and the two short “official source” labels. No unintended touch-control failure was observed in this bounded run.
- This run did not test mobile touchscreen hardware, alternative browsers, or an external trace.
