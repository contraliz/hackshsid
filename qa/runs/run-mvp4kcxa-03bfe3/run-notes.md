# QA run notes — gridshift-controls-mobile

- App: GridShift operations UI at `http://127.0.0.1:8001/`.
- Run: `run-mvp4kcxa-03bfe3`; viewport 390×844; 2026-10-26.
- Intent: check initial mobile layout, traffic preset selector options, warm-overhead control, and a completed replay.
- Actions: loaded Operations; captured initial view; selected Low, Normal, then High; opened More controls; set 2 warm overhead nodes; ran the resulting High scenario.
- Acceptance: controls remained usable; results rendered and exposed actual peak/shortfall; layout stayed within the 390 px viewport.
- Observed result: 4,052 generated requests; 32 base nodes and no added headroom; High traffic with seeded burst. At 17:24 and 267 offered GPUs, the 256-GPU fleet had 31 active, 0 warm-ready, 0 booting/warming, and 0 off; formula target 7 + 2 overhead = 9 stock nodes, with a 9-node stock deficit, 165.7-GPU projected readiness gap, and 11 GPUs of realized demand above installed capacity. This constrained-fleet overload is surfaced in the UI, not treated as a service guarantee.
- Measurements: 0 horizontal overflow, 0 broken images, 0 missing image alt text, 0 runtime events. Five small-target and three clipped-text signals were reviewed; the compact live note uses intentional ellipsis and the other text signals were only a few pixels and legible in the inspected frame. No confirmed defects.
- Outcome: pass for mobile controls and honest result/deficit display.
- Not run: mobile seek to peak, Node details view, hourly schedule flow, touch-device behavior. Desktop run covers node details and seeking.
- Inspected screenshots: [mobile controls](captures/mobile-controls.png), [mobile result and overload summary](captures/mobile-results.png).
