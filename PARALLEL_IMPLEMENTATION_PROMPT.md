# Parallel implementation assignment: operational experiment runner

Use **gpt-6-luna with high reasoning** for execution. Work directly if you are already that worker configuration.

Implement a reproducible batch experiment runner for the HackSHSID / GridShift operational simulation. Another team is implementing the simulator, interface, and launch fixes concurrently. Your work must stay within the independent file scope below.

## Current public baseline

- Repository: https://github.com/contraliz/hackshsid
- Branch: `main`
- Use the latest published `main` commit as the starting point and create a separate worktree/branch for your changes.
- Canonical policy: [`notes/model-specification.md`](notes/model-specification.md) (the full current policy; no duplicate policy file is needed).

## Context and isolation

- Attach AgentMem project `hackshsid`; consult the current policy, requirements, decisions, architecture, and implementation checkpoint. Use current source for actual API behavior.
- Start from the public repository's latest implementation commit when available. Use a separate Git worktree and your own branch. If the remote is not yet configured, inspect the existing local checkout and wait for an initial published source snapshot before depending on an isolated Git baseline; do not initialize a competing repository or reset anyone's files.
- Read the canonical complete policy Markdown file, expected at `docs/policy.md`, or follow the repository's canonical policy link if another path is used.
- The modeled inputs are synthetic request traffic, configured hardware inventory, renewable availability, and documented electricity prices applicable to Xiamen. Selected numeric settings may be illustrative assumptions. Preserve provenance labels.

## Authorized write scope

Create or edit only:

- `tools/operational_experiments.py`
- `tests/test_operational_experiments.py`
- `docs/operational-experiments.md`
- Synthetic output files in a new `results/operational-experiments/` directory, if useful and small.

Read other project files as needed. Do not edit the simulator, energy accounting, backend routes, frontend, launcher, packaging, dependencies, canonical policy, or shared AgentMem architecture/risks pages. If a named path is already owned by another agent, stop overlapping edits and report the conflict. Communicate simulator API defects as a compact blocker with evidence rather than changing its implementation.

## Deliverable

Build a CLI that calls the actual operational simulator and runs comparable scenarios under its supported always-on, reactive, and forecast controllers. Discover the current module/API and supported controller names from source; do not invent a second simulator or unsupported API contract.

- Use identical generated traffic, energy inputs, fleet settings, and seeds for controller comparisons. If generating scenarios independently per controller is unavoidable, verify deterministic regeneration or materialize and reuse one common trace.
- Support at least a normal day, a demand burst, a renewable shortfall, and a fleet-overload case where those controls are supported.
- Export a CSV summary and a readable Markdown report with scenario configuration, seed, controller, service completion, queue/wait statistics, flexible deadline outcomes, facility/grid energy, renewables, cost, emissions, and capacity shortfalls where available.
- Read metrics from the simulator's shared evaluator. Do not introduce conflicting cost or energy formulas or silently substitute missing metrics with zero.
- Calculate improvements only for meaningful comparisons; show absolute values and handle zero denominators. Display the source/assumption status of prices and carbon factors.
- Record controller failures and unsupported scenarios honestly. Do not label incomplete or infeasible runs as successful savings.
- Keep the CLI offline and avoid unnecessary dependencies.

## Verification and handoff

Run focused, meaningful checks of CLI argument handling, deterministic comparisons, output schemas, zero denominators, and failure reporting. Run a small real simulation batch once the implementation API is available. Report exact commands and observed results; never fabricate results or claim unrun checks passed.

Document the CLI's usage and assumptions in your assigned Markdown file. Commit your changes on your own branch, leaving integration to the main implementation owner. Do not push to or merge into the main branch. Record a separate AgentMem task receipt if available without rewriting another agent's shared pages.

Return a compact receipt containing status, files changed, branch and commit SHA, commands/results, simulator API assumptions, any blockers, and integration instructions.
