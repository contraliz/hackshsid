# Visual QA

## Reference comparison

The generated concepts are design references, not rendered evidence: [desktop](concepts/gridshift-desktop.png), [mobile](concepts/gridshift-mobile.png), and [infeasible state](concepts/gridshift-infeasible.png). The implemented screens were captured from the local app at 1584 × 1000 desktop and 390 × 844 mobile CSS pixels. Both reference and implementation screenshots were visually reviewed side by side.

| Area | Reference and rendered result | Decision |
| --- | --- | --- |
| Brand/header | Both use the GridShift wordmark, compute/energy subtitle, and synthetic-data marker. | Kept the generated concept's branding and restrained white/navy/blue/green palette. |
| Main desktop structure | Both use left-side scheduling controls, a prominent trade-off heading, hourly compute and energy charts, and a comparison table. | Kept that information order. The implemented charts retain the full hourly axis and comparison details, so the first desktop viewport reaches the beginning of the energy chart rather than the full results table. |
| Compute chart | Both distinguish an optimized line from the ASAP/baseline line and label hourly GPU use. | Used the real LP output and actual 256-GPU capacity; the concept's 1,024-GPU example is illustrative only. |
| Energy chart | Both separate renewable energy and grid use. | Added paired ASAP/optimized stacked bars so both methods' grid and renewable use can be compared on identical inputs. |
| Comparison | Both show side-by-side baseline and optimized results. | Expanded the table to cost, emissions, weighted objective, deadlines, unmet work, renewable use/curtailment, peak GPUs, and actual solver status. |
| Mobile layout | The concept uses large mobile cards and simplified summaries; the implementation stacks the actual form controls and preserves the complete comparison/job tables. | On narrow screens, control and text sizes remain usable, tables scroll within their own containers, charts stay on the page width, and axis label font size increases. At 390 px, the page has no horizontal overflow. |
| Infeasible state | Both use an amber warning panel, solver status, unmet work, and a restore action. | Kept that hierarchy but show the computed ASAP delivery/unmet amount and label all optimizer cells as unavailable. |

## Above-the-fold copy

The primary headline matches exactly: **“Schedule the work. Compare the trade-offs.”** The section titles “Hourly compute schedule”, “Hourly energy mix”, and “Comparison” are preserved. The implementation adds the selected scenario and seed metadata, the statement “Same workload and energy accounting for both methods”, measurement units, and a note explaining percentage signs. It labels the synthetic dataset explicitly. The generated sample values and “Baseline day” label were replaced with the prototype's reproducible seed-2026 case, “Balanced day”; this avoids presenting concept-only numbers as model results.

## Screenshots

- Desktop first viewport, 1584 × 1000: [`screenshots/desktop-balanced.png`](../screenshots/desktop-balanced.png)
- Desktop full page, 1584 × 1000: [`screenshots/desktop-full.png`](../screenshots/desktop-full.png)
- Mobile full page, 390 × 844: [`screenshots/mobile-balanced.png`](../screenshots/mobile-balanced.png)
- Demand-surge infeasible result, 1584 × 1000: [`screenshots/infeasible.png`](../screenshots/infeasible.png)

The Browser plugin was not available. Local rendered checks used Playwright with the installed Edge channel, and CUA/Edge accessibility-state interaction was also used to confirm the visible scenario and restore transitions. Screenshot dimensions and mobile scroll width were read from the browser. The page title, meaningful main content, solver state, console health, and control actions were checked; no external services or data were used.
