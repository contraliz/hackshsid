# QA run notes — gridshift-headroom-high-desktop

- App: GridShift operations UI at `http://127.0.0.1:8001/`.
- Run: `run-mvp4joih-e17a72`; viewport 1366×768; 2026-10-26.
- Intent: verify the fixed headroom control, High synthetic traffic preset, configurable warm overhead, completed replay, peak summary, and seeking from startup to the realized peak.
- Actions: loaded Operations; set 48 base nodes, 16 added headroom nodes, High (2×) traffic, 1 extra warm overhead node; disabled seeded bursts; ran the simulation; waited for result; sought to minute 1143.
- Acceptance: selectors and run completed; 64-node inventory remained fixed; result exposed the actual peak and node-state counts; seeking updated the selected replay minute.
- Observed result: 3,913 generated requests; realized offered peak 127 GPUs at 19:03. Forecast frame summary showed 16 active, 4 warm-ready, 3 booting, 0 warming, 41 off; formula target 6 + 1 overhead = 7 stock nodes, zero inactive-fleet gap, and 87.6-GPU bridge readiness gap. High demand created a real projected readiness gap even with spare fixed fleet.
- Measurements: 0 horizontal overflow, 0 broken images, 0 missing image alt text, 0 runtime events. Five small-target and one clipped-text signals were reviewed; these correspond to native slider/checkbox/logo sizes and the intentionally ellipsized compact traffic note, and were not confirmed as defects.
- Outcome: pass for tested controls and result flow; forecast gap is correctly surfaced. Not a workload-accuracy test.
- Not run: other controller comparisons, hourly schedule flow, package launch, touch-device behavior.
- Inspected screenshots: [configured controls](captures/configured-before-run.png), [completed result and startup replay](captures/completed-peak-summary.png), [seek to 19:03](captures/replay-minute-1143.png).
