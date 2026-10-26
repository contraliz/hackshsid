# QA run notes

- **Application:** GridShift, http://127.0.0.1:8001/
- **Run ID:** $(System.Collections.Hashtable.id)
- **Viewport:** 1366 × 768
- **Outcome:** pass for chart visibility

## Intent and result

Verify the Operations replay's per-node state timeline is present in the State timeline view, with ready-capacity context and Node details preserved. Explicit SVG/container height made the timeline visibly render before reserve details. The default and 01:10 captures show colored per-node history; 01:10 replay and no-wait state remained intact.

## Coverage and artifacts

The run's controls/actions and measurements are recorded in [steps.json](steps.json) and [measurements.json](measurements.json). The issue classification is in [issues.md](issues.md). Inspect named images in [captures](captures/); final acceptance evidence is in qa/runs/run-mvp8ekp8-e6f5d8 (desktop 1366 × 768) and qa/runs/run-mvp8et31-b0c0ae (mobile 390 × 844).

Mobile notes are not applicable to desktop runs. Controls exercised in this run used the default seed-2026 Forecast controller and zero extra headroom.
