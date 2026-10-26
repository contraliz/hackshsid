# QA run notes

- **Application:** GridShift, `http://127.0.0.1:8001/`
- **Run ID:** `run-mvp6rbi7-c41d61`
- **Date:** 2026-10-26
- **Viewport:** 1366 × 768
- **Outcome:** pass for the exercised desktop readiness and workload-label flow; no confirmed product defects.

## Intent and acceptance

Check the wait-aware policy's displayed assumptions, actual readiness/standby indicators, active/warm/off node states, and per-node workload labels at a meaningful peak time. Confirm the High traffic/fixed headroom controls and 19:03 replay seek work.

## Flow exercised

1. Set seed 2026, 48 base + 16 fixed headroom nodes, High 2× traffic, one warm-overhead node, default 25% active floor, and disabled the seeded burst.
2. Ran the simulation; the UI showed 3,913 requests and the 127-GPU 19:03 peak.
3. Sought to 19:03 and opened Node details. The UI showed 127 GPUs in use (all real-time for that selected minute), 18 peak active nodes in the forecast horizon, 1 warming node starting activation, 1 independent warm-stock target, and the current actual peak state of 16 active, 0 warm-ready, 1 booting, 1 warming, and 46 off. The displayed current readiness gap was 9.6 GPUs.
4. Captured the readiness panel and assumptions; switched to the explanatory details area.

## Evidence

- [High headroom result](captures/high-headroom-results.png)
- [Peak node details and work labels](captures/peak-node-work-labels.png)
- [Peak readiness/stock panel](captures/peak-readiness-and-stock.png)
- [Wait-aware equation and assumptions](captures/wait-aware-equation-and-assumptions.png)
- [Measurements](measurements.json)
- [Executed steps](steps.json)

The inspected node-detail screenshot confirms the independent warm-stock setting and separates the active target from observed state. The assumptions screenshot shows the forecast method and calibration limits. The later scroll capture is mostly whitespace and is not used as supporting evidence.

## Measurement and coverage

- Horizontal overflow: 0; broken images: 0; missing image alt: 0; runtime events: 0.
- Small-target flags concerned compact links, the checkbox, and slider; the clipped-text flag concerned a single-line synthetic-traffic description. No user-blocking issue was confirmed.
- The scenario exercises a predicted peak but does not prove zero queue wait under all seeds or cover package-level browser compatibility.
