# Verification evidence

All model inputs in this evidence are deterministic synthetic values generated for seed 2026. Outputs below are observations from the local implementation, not measured data-center results.

## Model and API checks

Command: `.\.venv\Scripts\python.exe -m pytest -q`

Observed result: **10 passed**.

Coverage includes:

- deterministic default inputs and repeatable optimizer metrics;
- solver `Optimal` status and independently checked release/deadline, job completion, per-job parallelism, GPU capacity, renewable bounds, and energy balance;
- one shared energy/cost/emissions evaluator for ASAP and optimized schedules;
- zero renewable availability;
- an isolated job moving to the only cheapest eligible hour;
- higher carbon weight lowering modeled emissions while holding workload fixed;
- profile changes for price-spike and renewable-shortage scenarios;
- a demand-surge LP returning `Infeasible` without relaxed or fabricated optimized work;
- clear rejection when the total GPU count cannot cover the real-time reservation;
- Flask API responses for optimal, infeasible, and invalid-input cases.

## Frontend build and scenario run

`npm run build` completed with Vite 8.3.5. `npm install` reported zero dependency vulnerabilities.

Browser checks used the local Edge channel through Playwright because the Browser plugin was not available in this session. The flow **Balanced day → Evening price spike → Demand surge → Restore baseline scenario** rendered the expected optimal price-spike result, honest infeasibility state with no optimized comparison, and restored default schedule. The invalid GPU-capacity request returned HTTP 422; `/api/health` returned 200. At 390 × 844 CSS pixels the document and body remained 390 pixels wide with no page-level horizontal overflow; SVG axis labels use a larger mobile size. The page title and main heading were correct, no error overlay appeared, and the final browser console pass had no errors or warnings after adding a local favicon.

Screenshots: [desktop first viewport](../screenshots/desktop-balanced.png), [desktop full page](../screenshots/desktop-full.png), [mobile full page](../screenshots/mobile-balanced.png), and [infeasible state](../screenshots/infeasible.png). See [visual-qa.md](../design/visual-qa.md) for reference comparison and copy differences.

`.\.venv\Scripts\python.exe scripts\run_experiments.py` wrote [scenario_comparison.csv](scenario_comparison.csv) and [scenario_comparison.md](scenario_comparison.md). The observed default case completed 6/6 jobs in both methods; ASAP grid cost was 481.43 CU and optimized cost was 464.29 CU (3.56% lower). Optimized grid emissions were 1103.91 kgCO₂e versus 1103.68 for ASAP (0.02% higher), so the default result does not claim a carbon improvement.

The evening price-spike case observed 7.90% lower cost with all deadlines met. The renewable-shortage case observed 3.23% lower cost with all deadlines met. The demand-surge case was infeasible; ASAP completed 3/6 jobs and left 1,471 GPU-hours unmet, and the LP provided no optimized schedule. These are reproducible outputs for the included model and seed only.

In the carbon-weight sensitivity, cost-only optimization observed 4.51% lower cost but 2.03% higher emissions than ASAP. At carbon weight 0.8 CU/kgCO₂e, observed cost was 3.03% lower and emissions 0.53% lower. See the CSV for raw values and solve times.

## Evidence boundaries

The LP verifies constraints that are represented in the model. It does not verify real-world preemption overhead, model serving latency, server affinity, networking, cooling beyond PUE, forecasts, grid telemetry, or production safety. Browser workflow and responsive-layout evidence is recorded after the local visual QA pass in the workspace screenshot set.

## Packaged Windows x64 executable — 2026-10-24

Reproducible build command: `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1`. It rebuilt the Vite assets, used pinned PyInstaller 6.22.3 with the existing Python 3.12.14 build environment, generated a one-file GUI EXE, and produced a folder-preserving ZIP. The final EXE is 55,657,883 bytes (SHA-256 `7B90E41598AADD616D32DEE21A1E72E23791FBB991D26F5F5D77F0D241B56901`); the ZIP is 55,205,720 bytes (SHA-256 `E2C6EAA48F8D8B7666D45EE8367D906860D0211A28E4930A28A7A99642FD8A89`). The archive contains `GridShift-Windows-x64/GridShift.exe` and `GridShift-Windows-x64/README-Run.txt`.

Copied the final EXE to a temporary folder outside the project root, in a path containing spaces, and launched it. The native status window opened Edge at a newly selected URL; the listener was bound to `127.0.0.1` only. `/api/health`, `/`, and the frontend JS/CSS assets returned HTTP 200. The packaged SciPy/HiGHS LP returned Optimal for Balanced day and Evening price spike; default independent validation passed with all 6 jobs completed, grid cost 481.43325 → 464.292 CU and operational emissions 1103.68075 → 1103.91175 kgCO₂e. Demand surge returned Infeasible without optimizer metrics; GPU capacity 1 returned HTTP 422. Close/Alt+F4 stopped the listener; a relaunch selected a different port.

Repository tests: `.\\.venv\\Scripts\\python.exe -m pytest -q` — **10 passed**. `.\\.venv\\Scripts\\python.exe -m compileall -q launcher.py server.py backend` — passed. There is no clean Windows VM test: this host has Python and Node installed, although the copied standalone EXE ran outside the source tree and the actual LP engine and static assets were exercised from the bundle. The EXE is unsigned; SmartScreen or antivirus may show a warning.

## Current dynamic simulation and onedir build — 2026-10-24

The current policy and implementation are in [`notes/model-specification.md`](../notes/model-specification.md). The dynamic route uses the same accepted Pro-priority LP hourly schedule for always-on, reactive, and forecast node controllers. LP-infeasible flexible candidates are not admitted. A fixed hourly GPU-hour allocation becomes minute GPU commitments; realtime requests can start only when projected active capacity over their non-preemptive run leaves those commitments intact. Minute energy counts delivered request GPUs and flexible GPUs once each; the fixed realtime LP curve constrains admission but is not charged as GPU activity in the dynamic trace.

Verification command: `.\.venv\Scripts\python.exe -m pytest -q` — **24 passed**. `npm run build` — passed with Vite 8.3.5. `py_compile` for `backend/dynamic_simulation.py` and `server.py` — passed. Focused cases verify all 3,060 GPU-hours complete by per-job deadlines under all three controllers at 32×8; a feasible 20-GPU-hour job remains protected while twenty same-minute 8-GPU requests queue and subsequently complete on a 96-GPU fleet; and an infeasible 100-GPU-hour one-hour job is reported not admitted. GPU-minute energy accounting equals request GPU-minutes plus delivered flexible GPU-hours × 60.

Rendered browser QA used Playwright with installed Microsoft Edge because no Browser plugin/skill was available and the computer-use/Node REPL browser runtimes failed to initialize their kernel assets. The source UI opened at `http://127.0.0.1:8000/`, page identity and content were correct, no framework overlay or page exceptions appeared, the original Pro-priority schedule ran, the 96-GPU preset updated controls, a forced request failure displayed `Failed to fetch`, then the same panel successfully ran the 32×8 simulation and rendered admission, energy/cost/emissions metrics, flexible delivery and deadline rows. At 390×844 pixels the document width remained 390 px; screenshots were saved outside the repository. The console's only error was the intentionally aborted fetch used to verify the error state; no other console errors occurred.

The current package was rebuilt with `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1` to `releases/GridShift-Windows-x64-onedir/GridShift.exe` plus `releases/GridShift-Windows-x64-onedir.zip`. The rebuilt ZIP was extracted and its EXE launched from a path containing spaces outside the source tree. The bundled page and current hashed JavaScript asset returned 200; `/api/health` reported healthy; `POST /api/dynamic-simulation` returned 3,060 GPU-hours scheduled and delivered, six of six deadlines met, and zero flexible misses. Closing the native window exited cleanly with no remaining process. This verifies the current host/package path, not a clean-VM installation or a signed executable. The older one-file release is retained as a legacy artifact and was not overwritten.

Reproducible current synthetic scenario values and their tariff/carbon-factor caveats are in [`dynamic-simulation-seed-2026.md`](dynamic-simulation-seed-2026.md). Forecast margins, request/workload mix and all power coefficients remain synthetic and uncalibrated; the 96-GPU default flexible workload is explicitly LP-infeasible and reported not admitted. These checks do not establish measured savings, a customer-specific Xiamen tariff, or production readiness.
