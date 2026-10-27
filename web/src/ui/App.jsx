import { useEffect, useMemo, useRef, useState } from 'react';
import { ComputeChart, EnergyChart, PolicyCostChart, PolicyEmissionsChart, PolicyEnergyMixCharts, PolicyQueueChart } from './Charts.jsx';
import { formatNumber, ScenarioControls } from './Controls.jsx';
import { ComparisonTable, InfeasibleState } from './Results.jsx';
import { RealtimeQueue } from './RealtimeQueue.jsx';
import { DynamicSimulation } from './DynamicSimulation.jsx';

const DEFAULTS = {
  scenario: 'baseline',
  gpu_count: 256,
  carbon_weight: 0.35,
  renewable_scale: 1,
  demand_scale: 1,
  realtime_active_equivalent_fraction: 1,
  priority_policy: 'pro_priority',
};

const SCENARIOS = [
  { id: 'baseline', label: 'Balanced day' },
  { id: 'price-spike', label: 'Evening price spike' },
  { id: 'renewables-shortage', label: 'Renewables shortage' },
  { id: 'demand-surge', label: 'Demand surge' },
];
const WORKSPACES = [
  { id: 'operations', label: 'Operations' },
  { id: 'schedule', label: 'Hourly schedule' },
];

async function requestSchedule(controls, signal) {
  const response = await fetch('/api/schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(controls),
    signal,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body;
}

function summarizeSimulationRun(simulationRun) {
  if (!simulationRun?.policies) return null;
  const policies = {};
  for (const key of ['always_on', 'reactive', 'forecast_v2']) {
    const policy = simulationRun.policies[key];
    if (!policy) return null;
    const queuePeakByHour = Array(24).fill(0);
    for (const frame of policy.state_trace ?? []) {
      const hour = Math.min(23, Math.max(0, Math.floor(Number(frame.minute) / 60)));
      queuePeakByHour[hour] = Math.max(queuePeakByHour[hour], Number(frame.queued_requests) || 0);
    }
    policies[key] = {
      metrics: policy.metrics,
      hourly_energy: (policy.hourly_grid_costs ?? []).map((row) => ({
        hour: Number(row.hour),
        grid_kwh: Number(row.grid_kwh) || 0,
        renewable_kwh: Number(row.renewable_used_kwh) || 0,
        facility_kwh: Number(row.facility_kwh) || 0,
        emissions_kg: Number(row.emissions_kg) || 0,
        cost_cny: Number(row.cost_cny) || 0,
        peak_queued_requests: queuePeakByHour[Number(row.hour)] || 0,
      })),
    };
  }
  return {
    seed: simulationRun.seed,
    nodes: simulationRun.nodes,
    gpus_per_node: simulationRun.gpus_per_node,
    fleet_gpus: simulationRun.fleet_gpus,
    traffic_profile_description: simulationRun.traffic_profile_description,
    headroom_description: simulationRun.headroom_description,
    warm_overhead_nodes: simulationRun.warm_overhead_nodes,
    assumptions: simulationRun.assumptions,
    policies,
  };
}

function App() {
  const [controls, setControls] = useState(DEFAULTS);
  const [result, setResult] = useState(null);
  const [runControls, setRunControls] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [workspace, setWorkspace] = useState('operations');
  const [simulationRun, setSimulationRun] = useState(null);
  const workspaceTabs = useRef({});

  async function runSchedule(nextControls = controls) {
    setBusy(true);
    setError('');
    const submittedControls = {
      ...nextControls,
      gpu_count: Number(nextControls.gpu_count),
      carbon_weight: Number(nextControls.carbon_weight),
      renewable_scale: Number(nextControls.renewable_scale),
      demand_scale: Number(nextControls.demand_scale),
      realtime_active_equivalent_fraction: Number(nextControls.realtime_active_equivalent_fraction),
    };
    try {
      const next = await requestSchedule(submittedControls);
      setResult(next);
      setRunControls(submittedControls);
    } catch (requestError) {
      setError(requestError.message || 'The scheduler could not complete this request.');
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    requestSchedule(DEFAULTS, controller.signal)
      .then((next) => {
        setResult(next);
        setRunControls(DEFAULTS);
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setError(requestError.message || 'The scheduler is unavailable.');
      });
    return () => controller.abort();
  }, []);

  const policyEnergy = useMemo(() => summarizeSimulationRun(simulationRun), [simulationRun]);

  const selectedLabel = useMemo(
    () => SCENARIOS.find((item) => item.id === controls.scenario)?.label ?? 'Balanced day',
    [controls.scenario],
  );
  const normalizedControls = {
    ...controls,
    gpu_count: Number(controls.gpu_count),
    carbon_weight: Number(controls.carbon_weight),
    renewable_scale: Number(controls.renewable_scale),
    demand_scale: Number(controls.demand_scale),
    realtime_active_equivalent_fraction: Number(controls.realtime_active_equivalent_fraction),
  };
  const controlsChanged = Boolean(runControls && JSON.stringify(runControls) !== JSON.stringify(normalizedControls));

  function updateControl(key, value) {
    setControls((current) => ({ ...current, [key]: value }));
  }

  function updateJobTier(id, tier) {
    setControls((current) => {
      const base = current.job_tiers ?? Object.fromEntries((result?.case?.jobs ?? []).map((job) => [job.id, job.tier]));
      return { ...current, job_tiers: { ...base, [id]: tier } };
    });
  }

  function restoreBaseline() {
    setControls(DEFAULTS);
    runSchedule(DEFAULTS);
  }

  function handleWorkspaceKeyDown(event, index) {
    let nextIndex = index;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % WORKSPACES.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (index - 1 + WORKSPACES.length) % WORKSPACES.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = WORKSPACES.length - 1;
    else return;
    event.preventDefault();
    const nextWorkspace = WORKSPACES[nextIndex].id;
    setWorkspace(nextWorkspace);
    workspaceTabs.current[nextWorkspace]?.focus();
  }

  return (
    <div className="app-shell" id="top">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GridShift home">GridShift</a>
        <span className="topbar-divider" aria-hidden="true" />
        <span className="product-name">Compute &amp; energy scheduler</span>
        <span className="synthetic-label"><span className="synthetic-dot" />Synthetic data</span>
      </header>

      <div className="dashboard-content">
        <nav className="dashboard-tabs" role="tablist" aria-label="GridShift workspaces">
          {WORKSPACES.map((tab, index) => <button
            key={tab.id}
            ref={(element) => { workspaceTabs.current[tab.id] = element; }}
            id={`${tab.id}-tab`}
            type="button"
            role="tab"
            aria-selected={workspace === tab.id}
            aria-controls={`${tab.id}-panel`}
            tabIndex={workspace === tab.id ? 0 : -1}
            className={`dashboard-tab${workspace === tab.id ? ' is-selected' : ''}`}
            onClick={() => setWorkspace(tab.id)}
            onKeyDown={(event) => handleWorkspaceKeyDown(event, index)}
          >{tab.label}</button>)}
        </nav>

        <section id="operations-panel" className="workspace-panel operations-workspace" role="tabpanel" aria-labelledby="operations-tab" hidden={workspace !== 'operations'}>
          <DynamicSimulation onSimulationResult={setSimulationRun} />
        </section>

        <section id="schedule-panel" className="workspace-panel schedule-workspace" role="tabpanel" aria-labelledby="schedule-tab" hidden={workspace !== 'schedule'}>
        <div className="page-frame">
        <aside className="control-rail" aria-label="Schedule controls">
          <div className="control-rail-inner">
            <ScenarioControls
              controls={controls}
              scenarios={SCENARIOS}
              onChange={updateControl}
              onRun={() => runSchedule()}
              busy={busy}
            />
          </div>
        </aside>

          <main className="main-content">
          <section className="page-heading" aria-labelledby="page-title">
            <div>
              <h1 id="page-title">{result?.optimizer?.priority_policy_label ?? 'Pro-priority'} scheduling.</h1>
            </div>
            <div className="case-meta">
              <span>{result?.case?.scenario_label ?? selectedLabel}</span>
              <span className="case-meta-dot" aria-hidden="true">·</span>
              <span>Seed {result?.case?.seed ?? 2026}</span>
            </div>
          </section>

          {error && (
            <div className="error-banner" role="alert">
              <strong>Could not run the schedule.</strong>
              <span>{error}</span>
            </div>
          )}

          {!result && !error && <div className="loading-state" aria-live="polite">Preparing the synthetic day…</div>}

          {result && (
            <>
              {controlsChanged && (
                <div className="stale-results-banner" role="status">
                  Controls changed. Results below show the last completed run; run the schedule to refresh them.
                </div>
              )}
              {result.optimizer.status === 'Optimal' && result.optimized ? (
                <>
                  <section className="chart-section" aria-labelledby="compute-title">
                    <div className="section-title-row">
                      <div>
                        <h2 id="compute-title">Hourly compute schedule</h2>
                        <p className="section-unit">Concurrent GPU use · GPUs per slot</p>
                      </div>
                        <span className="solver-status"><span className="status-dot" />{result.optimizer.status} · {result.optimizer.priority_policy_label}</span>
                    </div>
                    <ComputeChart result={result} />
                  </section>

                  <section className="chart-section energy-section" aria-labelledby="energy-title">
                    <div className="section-title-row">
                      <div>
                        <h2 id="energy-title">Hourly energy mix</h2>
                        <p className="section-unit">Facility electricity · kWh per slot</p>
                      </div>
                      <div className="legend-inline" aria-label="Energy chart legend">
                        <span><i className="legend-swatch renewable" />Renewable</span>
                        <span><i className="legend-swatch grid" />Grid</span>
                        <span><i className="method-swatch baseline-method" />Priority ASAP</span>
                        <span><i className="method-swatch optimized-method" />{result.optimizer.priority_policy_label} LP</span>
                      </div>
                    </div>
                    <EnergyChart result={result} />
                  </section>

                  <section className="chart-section policy-comparison-section" aria-labelledby="policy-comparison-title">
                    <div className="section-title-row">
                      <div>
                        <h2 id="policy-comparison-title">Hourly node-controller comparison</h2>
                        <p className="section-unit">Last completed simulation · Always-on, Reactive, and Forecast v2</p>
                      </div>
                    </div>
                    {!policyEnergy && <p className="policy-comparison-status" role="status">Run the simulation in Operations to populate these charts with its controller replay data.</p>}
                    {policyEnergy && <>
                      <p className="policy-comparison-context">
                        Source: the last completed Operations simulation · seed {policyEnergy.seed} · {policyEnergy.nodes} nodes × {policyEnergy.gpus_per_node} GPUs ({policyEnergy.fleet_gpus} total) · {policyEnergy.traffic_profile_description} · {policyEnergy.headroom_description} · {policyEnergy.warm_overhead_nodes}-node warm target. Every chart summarizes that run's actual controller energy rows and minute-level request queues. The hourly LP schedule is a separate model.
                      </p>
                      <div className="policy-chart-block">
                        <div className="section-title-row">
                          <div><h3>Electricity use by hour</h3><p className="section-unit">Grid imports + renewable electricity used · kWh</p></div>
                        </div>
                        <PolicyEnergyMixCharts result={policyEnergy} />
                      </div>
                      <div className="policy-chart-block">
                        <div className="section-title-row">
                          <div><h3>Grid emissions by hour</h3><p className="section-unit">Grid imports × the simulation's 0.55 kg CO₂/kWh factor</p></div>
                        </div>
                        <PolicyEmissionsChart result={policyEnergy} />
                      </div>
                      <div className="policy-chart-block">
                        <div className="section-title-row">
                          <div><h3>Grid cost by hour</h3><p className="section-unit">Grid imports × the simulation's illustrative tariff · CNY</p></div>
                        </div>
                        <PolicyCostChart result={policyEnergy} />
                      </div>
                      <div className="policy-chart-block">
                        <div className="section-title-row">
                          <div><h3>Peak real-time queue by hour</h3><p className="section-unit">Highest queued requests recorded during each simulation hour</p></div>
                        </div>
                        <PolicyQueueChart result={policyEnergy} />
                      </div>
                    </>}
                  </section>

                  <details className="schedule-disclosure">
                    <summary>Comparison results and baseline</summary>
                    <section className="results-section" aria-labelledby="comparison-title">
                      <div className="section-title-row results-heading">
                        <div>
                          <h2 id="comparison-title">Comparison</h2>
                          <p className="section-unit">Same priority tiers, deadlines, and energy accounting</p>
                        </div>
                        <span className="solver-caption">{result.optimizer.solver}</span>
                      </div>
                      <ComparisonTable result={result} />
                      {!result.comparison.comparable && (
                        <p className="comparison-note" role="status">
                          The ASAP baseline missed one or more deadlines. Percent changes are hidden because the delivered work is not comparable.
                        </p>
                      )}
                    </section>
                  </details>
                </>
              ) : (
                <InfeasibleState result={result} onRestore={restoreBaseline} />
              )}

              <details className="schedule-disclosure policy-diagnostic-disclosure">
                <summary>Same-input policy diagnostic</summary>
                <PolicyDiagnostic result={result} />
              </details>

              <details className="schedule-disclosure">
                <summary>Request priority queue</summary>
                <RealtimeQueue controls={controls} scheduleResult={result} />
              </details>

              <details className="schedule-disclosure">
                <summary>Flexible jobs and commitments</summary>
                <section className="workload-section" aria-labelledby="workload-title">
                  <div className="section-title-row">
                    <div>
                      <h2 id="workload-title">Flexible jobs</h2>
                      <p className="section-unit">Set simulated subscriber tier · release inclusive, deadline exclusive</p>
                    </div>
                  </div>
                  <div className="job-table-wrap">
                  <table className="job-table">
                    <thead>
                      <tr><th>Job</th><th>Tier</th><th>Release</th><th>Deadline</th><th>Demand</th><th>Priority ASAP</th><th>{result.optimizer.priority_policy_label} LP</th><th>Work-weighted avg execution</th></tr>
                    </thead>
                    <tbody>
                      {result.case.jobs.map((job, index) => {
                        const asap = result.baseline.jobs[index];
                        const opt = result.optimizer.success ? result.optimizer.jobs[index] : null;
                        return (
                          <tr key={job.id}>
                            <th scope="row">{job.name}</th>
                            <td>
                              <select aria-label={`${job.name} tier`} value={controls.job_tiers?.[job.id] ?? job.tier} onChange={(event) => updateJobTier(job.id, event.target.value)}>
                                <option value="pro">Pro</option><option value="standard">Standard</option>
                              </select>
                            </td>
                            <td>{String(job.arrival).padStart(2, '0')}:00</td>
                            <td>{String(job.deadline).padStart(2, '0')}:00</td>
                            <td>{formatNumber(job.gpu_hours)} GPU-h</td>
                            <td>{formatNumber(asap.delivered_gpu_hours)} GPU-h</td>
                            <td>{opt ? `${formatNumber(opt.delivered_gpu_hours)} GPU-h` : 'No feasible schedule'}</td>
                            <td>{opt?.average_execution_hour === null || opt?.average_execution_hour === undefined ? '—' : `${formatNumber(opt.average_execution_hour, 1)} h`}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  </div>
                </section>
              </details>

              <details className="assumptions" id="assumptions">
                <summary>
                  <span>Model assumptions</span>
                  <Chevron />
                </summary>
                <div className="assumptions-content">
                  <ul>
                    <li>Flexible work is divisible and preemptible; fractional GPU-hours are allowed.</li>
                    <li>The default Pro-priority LP orders Pro flexible jobs by release time then row order and lexicographically minimizes each Pro job’s GPU-hour-weighted execution time before energy cost. The energy-only diagnostic omits those earliness stages. Job completion, capacity, per-job parallelism, and every deadline stay hard constraints for both policies.</li>
                    <li>Pro real-time requests jump queued Standard requests when a fitting GPU reservation becomes free. The next fitting request can backfill past a request that is too large for current free GPUs. Running work is never preempted. Continuous Pro arrivals can delay Standard requests.</li>
                    <li>Real-time simulation uses the selected hour’s fixed reservation and does not add request GPUs to daily facility energy a second time. It is not actual inference or an SLA measurement. Pro/Standard are simulated labels; no real account, subscription, or billing system exists.</li>
                    <li>Each hour, facility load is PUE × (fixed IT base power + active-equivalent real-time GPU power + flexible GPU power). Capacity is still reserved against the full real-time GPU count. Active-equivalent use defaults to that reservation and is an explicit modeling assumption, not telemetry.</li>
                    <li>Base IT power (18 kW), incremental GPU power (0.42 kW per active-equivalent GPU), PUE (1.25), prices, carbon intensity, workload, and renewable availability are synthetic demo assumptions, not measurements.</li>
                    <li>The legacy hourly model still requires at least 100 GPUs for its current synthetic reservation profile. The separate node-state simulator offers an illustrative 96-GPU inventory preset; its generated request peaks may exceed that inventory and overload is reported.</li>
                    <li>“Optimal” means optimal for this LP and these inputs. Server affinity, networking, batteries, thermal dynamics, and production deployment are out of scope.</li>
                  </ul>
                  <p>Cost is shown in synthetic cost units (CU); emissions are kgCO₂e from grid imports.</p>
                </div>
              </details>
            </>
          )}

          <footer className="page-footer">
            <span>GridShift · HackSHSID Track 2 prototype</span>
            <span>Deterministic synthetic workload · seed 2026</span>
          </footer>
        </main>
      </div>
        </section>
    </div>
    </div>
  );
}

function PolicyDiagnostic({ result }) {
  const policies = result.policy_diagnostic?.policies ?? {};
  const pro = policies.pro_priority;
  const energy = policies.energy_only;
  if (!pro || !energy) return null;
  return (
    <div className="comparison-table-wrap policy-diagnostic">
      <h3>Same-input policy diagnostic</h3>
      <p className="comparison-footnote">Both LP policies use the exact same case and shared energy evaluator. This comparison is diagnostic; the selected policy is {result.policy_diagnostic.selected_policy_label}.</p>
      <table className="comparison-table">
        <thead><tr><th>Measure</th><th>Pro-priority LP</th><th>Energy-only LP</th></tr></thead>
        <tbody>
          <tr><th scope="row">Grid cost</th><td>{formatNumber(pro.metrics?.grid_cost_units, 2)} CU</td><td>{formatNumber(energy.metrics?.grid_cost_units, 2)} CU</td></tr>
          <tr><th scope="row">Grid emissions</th><td>{formatNumber(pro.metrics?.grid_emissions_kg_co2e, 1)} kgCO₂e</td><td>{formatNumber(energy.metrics?.grid_emissions_kg_co2e, 1)} kgCO₂e</td></tr>
          <tr><th scope="row">Facility energy</th><td>{formatNumber(pro.metrics?.total_facility_energy_kwh, 1)} kWh</td><td>{formatNumber(energy.metrics?.total_facility_energy_kwh, 1)} kWh</td></tr>
          <tr><th scope="row">Grid imports</th><td>{formatNumber(pro.metrics?.grid_import_kwh, 1)} kWh</td><td>{formatNumber(energy.metrics?.grid_import_kwh, 1)} kWh</td></tr>
          <tr><th scope="row">Renewable used / curtailed</th><td>{formatNumber(pro.metrics?.renewable_used_kwh, 1)} / {formatNumber(pro.metrics?.renewable_curtailed_kwh, 1)} kWh</td><td>{formatNumber(energy.metrics?.renewable_used_kwh, 1)} / {formatNumber(energy.metrics?.renewable_curtailed_kwh, 1)} kWh</td></tr>
          <tr><th scope="row">Deadlines met</th><td>{pro.metrics?.deadlines_met} / {pro.metrics?.deadline_count}</td><td>{energy.metrics?.deadlines_met} / {energy.metrics?.deadline_count}</td></tr>
          <tr><th scope="row">Peak reserved-capacity use / installed</th><td>{formatNumber(pro.metrics?.peak_reserved_gpu_utilization, 1)} / {result.case.gpu_count} GPUs</td><td>{formatNumber(energy.metrics?.peak_reserved_gpu_utilization, 1)} / {result.case.gpu_count} GPUs</td></tr>
          <tr><th scope="row">Peak active-equivalent power use</th><td>{formatNumber(pro.metrics?.peak_active_equivalent_gpu_power_use, 1)} GPU-equivalents</td><td>{formatNumber(energy.metrics?.peak_active_equivalent_gpu_power_use, 1)} GPU-equivalents</td></tr>
          <tr><th scope="row">Status</th><td>{pro.status}</td><td>{energy.status}</td></tr>
        </tbody>
      </table>
      <p className="comparison-footnote">Per-job “average execution” is GPU-hour-weighted execution time, not the job's completion time. No SLA values or SLA claims are modeled.</p>
    </div>
  );
}

function Chevron() {
  return <svg className="chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 6 4.5 4 4.5-4" /></svg>;
}

export default App;
