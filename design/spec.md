# GridShift interface design specification

The generated primary desktop, mobile continuation, and infeasible-result state concepts are the visual references for this local prototype. The desktop concept is the primary specification; mobile and infeasible concepts clarify responsive and error states. The generated illustrative numbers are not product data and must not appear as calculated results.

## Screen and copy

- Product: GridShift, an interactive local operations research prototype for AI data-center compute and energy co-scheduling.
- First viewport: simple header; page title “Schedule the work. Compare the trade-offs.”; left scenario/control rail; right primary schedule chart; energy chart; compact baseline/optimized comparison; visible assumptions disclosure.
- Primary controls: scenario selector, total GPUs, carbon weight, renewable availability scale, flexible-work demand scale, and Run schedule. The last two are useful real input controls; they can appear below the fold or in a compact “Scenario adjustments” area while preserving the main concept.
- Charts: 24-hour hourly compute load (baseline dashed slate, optimized solid blue); aligned hourly energy mix (green renewable use plus slate grid import). Use accurate hour labels and unit-bearing axes.
- Results: baseline and optimized grid cost, operational grid emissions, deadline completion/unmet work, renewable use/curtailment, solver status, and solve time. Never show optimized results when the LP is infeasible.
- Disclosure: model assumptions and limitations are readable without leaving the workspace.
- State copy: when infeasible, explain that the inputs cannot fit job release/deadline windows and GPU capacity, show the solver status, and remove savings claims.

## Design system extracted from concept

- Canvas: true white (#FFFFFF); content text deep navy (#0E1B36); secondary labels slate (#61718A); fine borders/grid lines pale blue-gray (#D9E2EC).
- Semantics: optimized compute/primary action bright blue (#1677F2); baseline neutral slate (#8394A8); renewable energy green (#43B978); infeasibility uses a subtle amber rule/background.
- Typography: editorial sans-serif for headings, readable neutral sans-serif throughout; large dark title; moderate section heads; compact but deliberate labels and control text. No browser-default control text.
- Spacing: airy outside the chart area; aligned main columns; moderate chart density; simple 4–6px control corners; thin borders; no gradients, shadows, decorative pills, or nested card grids.
- Components: simple top bar, vertical control rail, select/input/slider, primary button, responsive chart frames with native SVG marks/axes, comparison table, disclosure, clear warning/result state.
- Interaction: control changes are real state; Run schedule calls the local optimizer. Scenario adjustments must flow into both baseline and optimized evaluation.

## Responsive behavior

At phone width, header and controls stack; keep each chart legible with fewer visible tick labels while retaining all 24 hourly values; results become a compact comparison table or stacked rows; assumptions remain reachable. Avoid horizontal page overflow.

## Allowed above-the-fold copy

GridShift; Compute & energy scheduler; Synthetic data; Schedule the work. Compare the trade-offs.; scenario selector; Total GPUs; Carbon weight; Run schedule; Hourly compute schedule; Hourly energy mix; Comparison; Baseline; Optimized; Grid cost; Grid emissions; Deadlines met; Solver status; Model assumptions. Additional labels may be introduced only where needed to operate real scenario controls or explain a real infeasibility state.

## Known concept deviations permitted for correctness

- Replace generated mock metrics with solver results from the selected synthetic case.
- Fix generated chart tick duplication: display 00 through 23 once each, or label every 2–4 hours while preserving 24 data points.
- Provide a scientifically accurate unit for energy and cost; the source model's power formula returns kWh/slot, and actual reporting uses kWh and kgCO2.
- The image generator's error screen included fabricated shortfall values. Compute any reported unmet work from the actual input/solver result or omit it.
