# QA run notes — gridshift-node-details-desktop

- App: GridShift operations UI at `http://127.0.0.1:8001/`.
- Run: `run-mvp4lhuc-4f605e`; viewport 1366×768; 2026-10-26.
- Intent: inspect actual node work labels and warm-reserve data after seeking to the known realized High/no-burst peak.
- Actions: ran 48 base + 16 added nodes, High (2×), bursts off, 1 warm overhead; waited for result; sought to minute 1143; opened Node details and scrolled the node panel to expose the selected-minute readout.
- Acceptance: result and seek completed; work labels and per-node GPU counts distinguish real-time and flexible allocations from power states; reserve readout distinguishes ready warm nodes, booting, and activating nodes.
- Observed result at 19:03: 127 offered GPUs; 16 active, 4 warm-ready, 3 booting, 0 warming, and 41 off in a 64-node fleet. Desired stock 7 (formula 6 plus overhead 1); 3 stock nodes not ready yet, 0 inactive-fleet shortage, 1.0 active spare GPUs, 87.6-GPU readiness gap. The screenshot also shows per-node Real-time badges and counts.
- Measurements: 0 horizontal overflow, 0 broken images, 0 missing image alt text, 0 runtime events. Five small-target signals and the intentional compact traffic-note ellipsis were not confirmed defects.
- Outcome: pass for the selected-minute node details and reserve explanation. The readiness gap remains visible and is not hidden by headroom.
- Not run: touch-device behavior, browser comparison against a visual baseline, hourly schedule flow, package launch.
- Inspected screenshot: [peak node details](captures/peak-node-details.png).
