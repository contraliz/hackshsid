# Contribution assignment: reproducible simulation experiments

Contribute to the public GridShift / HackSHSID project:
https://github.com/contraliz/hackshsid

The main team is actively implementing the operational simulator, flexible-job coordination, frontend, and Windows launcher. Your independent task is a batch experiment CLI and report exporter. Stay within your assigned files to avoid conflicts.

## Start and context

1. Clone the repository and fetch the latest `main`. Create your own branch, such as `contrib/operational-experiments`, and work in a separate checkout or Git worktree. Do not push to `main`.
2. Read repository instructions, `README.md`, and the full policy at `notes/model-specification.md` (or follow the canonical policy link if it moved).
3. If you have access to an existing, correctly registered AgentMem `hackshsid` project, consult it. If unavailable, use the repository policy and document that limitation; do not invent or overwrite an AgentMem project binding.
4. Use GPT-6 Luna with high reasoning for execution if your environment supports that configuration. Disclose an unavailable required configuration rather than silently claiming it was used.

## Your deliverable

Implement an offline-friendly Python CLI that runs reproducible operational-simulation comparisons and writes CSV and Markdown reports. The existing API is `POST /api/dynamic-simulation`; inspect the current handler and response schema before coding. Prefer consuming this API with a configurable local `--base-url` so backend implementation changes do not require you to edit shared files.

- Support configurable seeds and output directory.
- Compare the simulator's actual supported always-on, reactive, and forecast controllers on identical traffic, hardware, renewable inputs, and prices. If one API call already returns all controllers for one common trace, reuse that result.
- Include normal traffic, a traffic burst, and a capacity-limited scenario using supported input options. Include a renewable-shortfall case only if the API supports it; report unsupported options explicitly.
- Export actual available metrics: completion/rejection, queue and waiting time, flexible-job admission/completion/deadlines, capacity shortfalls, facility/grid energy, renewable use, cost, emissions, and node-state summaries.
- Preserve source and assumption labels for traffic, hardware power, Xiamen tariff references/proxy prices, and carbon factors.
- Use the simulator's reported metrics and shared accounting. Do not invent a second simulator, substitute absent values with zero, fabricate savings, or hide overloaded/infeasible runs.
- Show absolute values and percentage comparisons only when valid; handle zero denominators.
- Avoid unnecessary dependencies and external services.

## Exclusive file scope

You may create or edit only:

- `tools/operational_experiments.py`
- `tests/test_operational_experiments.py`
- `docs/operational-experiments.md`
- Small synthetic example outputs under `results/operational-experiments/`

Read other files freely. Do not edit backend modules, routes, frontend, launcher, dependency files, canonical policy, existing tests, or shared AgentMem architecture/risks pages. If an assigned file is already being edited by someone else, report the conflict before writing.

The backend/API is still evolving. Fetch updates when necessary, tolerate explicitly documented optional result fields, and report any missing required API capability to the main team with a concise example. Do not repair shared backend code in this contribution.

## Verification and delivery

Add focused tests for parsing actual API result shapes, CLI options, failed scenarios, deterministic inputs, output schemas, and zero denominators. Use fixtures honestly and distinguish fixture tests from a real API run. Once the current server is available, run a small real batch and document commands and actual results. Never claim checks you did not run.

Document usage, supported scenarios, API assumptions, and limitations in your assigned guide. Commit on your branch, push that branch to your fork, and open a pull request to `contraliz/hackshsid` if GitHub access is available; otherwise provide a commit/patch for integration. Do not merge it yourself. Include only your assigned files.

Return a compact receipt with status, branch/fork/PR or patch, commit SHA, files changed, verification results, a sample report, and precise remaining blockers. The deadline is midnight on 2026-10-24 in Asia/Shanghai, so prioritize a usable CLI and honest comparisons over presentation polish.
