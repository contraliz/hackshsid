import { useEffect, useState } from 'react';
import { formatNumber } from './Controls.jsx';
import { LiveTrafficView } from './LiveTrafficView.jsx';
import { NodePowerView } from './NodePowerView.jsx';
import { SavingsReport } from './SavingsReport.jsx';

const LABELS = {
  facility_kwh: ['Facility energy', 'kWh'], grid_kwh: ['Grid imports', 'kWh'],
  renewable_used_kwh: ['Renewable used', 'kWh'], renewable_curtailed_kwh: ['Renewable curtailed', 'kWh'],
  cost_cny: ['Illustrative grid cost', 'CNY'], emissions_kg: ['Grid CO₂', 'kg CO₂'],
  requests_completed: ['Completed requests', ''], requests_queued_at_horizon: ['Queued at horizon', ''],
  requests_rejected: ['Rejected requests', ''], requests_waited: ['Requests with nonzero queue wait', ''], mean_wait_minutes: ['Mean queue wait', 'min'],
  p95_wait_minutes: ['P95 queue wait', 'min'], mean_completion_latency_minutes: ['Mean completion latency', 'min'],
  latency_allowance_met: ['Illustrative response allowances met', 'requests'], peak_active_nodes: ['Peak active nodes', ''],
  max_forecast_capacity_shortfall_gpus: ['Peak forecast fleet shortfall', 'GPUs'], forecast_shortfall_minutes: ['Forecast shortfall intervals', '5-min intervals'],
  max_readiness_capacity_shortfall_gpus: ['Peak readiness shortfall', 'GPUs'], max_pre_warm_active_shortfall_gpus: ['Peak shortfall before warm activation', 'GPUs'],
  max_target_warm_fleet_shortfall_nodes: ['Peak legacy scalar target gap', 'nodes'], max_target_warm_nodes: ['Peak legacy scalar warm target (diagnostic)', 'nodes'],
  max_warm_stock_shortfall_nodes: ['Peak warm-buffer fleet deficit', 'nodes'], max_warm_ready_deficit_nodes: ['Peak warm stock not ready yet', 'nodes'],
  peak_offered_fleet_shortfall_gpus: ['Peak realized demand above fleet', 'GPUs'], offered_fleet_shortfall_minutes: ['Realized fleet overload', 'min'],
  flexible_jobs_admitted: ['Flexible jobs admitted', 'jobs'], flexible_jobs_deadline_met: ['Flexible deadlines met', 'jobs'],
  flexible_gpu_hours_scheduled: ['Flexible work scheduled', 'GPU·h'], flexible_gpu_hours_delivered: ['Flexible work delivered', 'GPU·h'],
  flexible_gpu_hours_unmet: ['Flexible work unmet / not admitted', 'GPU·h'], flexible_commitment_missed_gpu_minutes: ['Flexible work left at deadline', 'GPU·min'],
};

function HourlyGridCosts({ policy, selectedPolicy }) {
  const rows = policy?.hourly_grid_costs || [];
  if (!rows.length) return null;
  const total = rows.reduce((sum, row) => sum + row.cost_cny, 0);
  return <details className="simulation-data-disclosure grid-cost-disclosure">
    <summary>Grid cost by hour · {selectedPolicy} · ¥{formatNumber(total, 2)} for the day</summary>
    <p className="grid-cost-note">Illustrative imported-grid energy cost after hourly renewable use; excludes demand/capacity fees and is not a customer bill. Times are local China Standard Time (UTC+8).</p>
    <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Hour</th><th>Tariff band</th><th>Rate (CNY/kWh)</th><th>Grid imports (kWh)</th><th>Energy cost (CNY)</th></tr></thead><tbody>
      {rows.map((row) => <tr key={row.hour}><td>{String(row.hour).padStart(2, '0')}:00–{String((row.hour + 1) % 24).padStart(2, '0')}:00</td><td>{row.tariff_period}</td><td>{formatNumber(row.rate_cny_kwh, 8)}</td><td>{formatNumber(row.grid_kwh, 3)}</td><td>{formatNumber(row.cost_cny, 2)}</td></tr>)}
    </tbody><tfoot><tr><th colSpan="3">Day total</th><td>{formatNumber(rows.reduce((sum, row) => sum + row.grid_kwh, 0), 3)}</td><td>{formatNumber(total, 2)}</td></tr></tfoot></table></div>
  </details>;
}

export function DynamicSimulation({ onSimulationResult }) {
  const [controls, setControls] = useState({ nodes: 40, headroom_nodes: 0, gpus_per_node: 8, seed: 2026, traffic_profile: 'normal', warm_overhead_nodes: 2, forecast_alpha: 0.3, margin_fraction: 0.15, margin_floor_gpus: 4, min_active_fraction: 0.25 });
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedPolicy, setSelectedPolicy] = useState('forecast_v2');
  const [minute, setMinute] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);

  const selectedReplay = result?.policies?.[selectedPolicy]?.replay;
  const lastMinute = Math.max(0, (selectedReplay?.frames?.length || 1) - 1);

  useEffect(() => {
    if (!playing || !selectedReplay?.frames?.length) return undefined;
    const timer = window.setInterval(() => {
      setMinute((current) => {
        if (current >= lastMinute) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 1000 / speed);
    return () => window.clearInterval(timer);
  }, [playing, selectedReplay, lastMinute, speed]);

  async function run(event) {
    event.preventDefault();
    setPlaying(false); setMinute(0);
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/dynamic-simulation', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...controls, nodes: Number(controls.nodes), gpus_per_node: Number(controls.gpus_per_node), seed: Number(controls.seed), forecast_alpha: Number(controls.forecast_alpha), margin_fraction: Number(controls.margin_fraction), margin_floor_gpus: Number(controls.margin_floor_gpus), min_active_fraction: Number(controls.min_active_fraction) }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
      setResult(body);
      onSimulationResult?.(body);
      setSelectedPolicy(body.selected_policy && body.policies?.[body.selected_policy] ? body.selected_policy : 'forecast_v2');
      setMinute(0);
    } catch (e) { setError(e.message || 'Simulation failed.'); }
    finally { setBusy(false); }
  }

  return (
    <section className="dynamic-dashboard" aria-labelledby="dynamic-title">
      <div className="dynamic-dashboard-heading"><div><h1 id="dynamic-title">Data center operations</h1><p>Replay the same seeded request trace across three node controllers.</p></div><span className="dynamic-synthetic-badge">Synthetic replay</span></div>
      <form className="dynamic-controls" onSubmit={run}>
        <div className="dynamic-primary-controls">
          <label htmlFor="dynamic-nodes">Nodes<input id="dynamic-nodes" type="number" min="2" max="64" value={controls.nodes} onChange={(e) => setControls({ ...controls, nodes: e.target.value })} /></label>
          <label htmlFor="dynamic-gpus">GPUs per node<input id="dynamic-gpus" type="number" min="1" max="16" value={controls.gpus_per_node} onChange={(e) => setControls({ ...controls, gpus_per_node: e.target.value })} /></label>
          <label htmlFor="dynamic-traffic-profile">Traffic level<select id="dynamic-traffic-profile" value={controls.traffic_profile} onChange={(e) => setControls({ ...controls, traffic_profile: e.target.value })}><option value="low">Low · 0.5×</option><option value="normal">Normal · 1×</option><option value="high">High · 2×</option></select></label>
          <label htmlFor="dynamic-headroom">Fleet headroom<select id="dynamic-headroom" value={controls.headroom_nodes} onChange={(e) => setControls({ ...controls, headroom_nodes: Number(e.target.value) })}><option value="0">Standard inventory</option><option value="16" disabled={Number(controls.nodes) > 48}>Add 16 fixed nodes</option></select></label>
          <button className="run-button" disabled={busy}>{busy ? 'Simulating…' : 'Run simulation'}</button>
        </div>
        <p className="dynamic-traffic-note">Every run uses the heavy-tailed, bursty realistic traffic shape: sizes and durations are log-normal, arrivals are over-dispersed and autocorrelated, and the interactive/batch mix shifts across the day. The traffic level scales the arrival rate of that same day shape.</p>
        <details className="dynamic-tuning">
          <summary>More controls <span>Traffic, forecast and reserve assumptions</span></summary>
          <div className="dynamic-secondary-controls">
            <label htmlFor="dynamic-alpha">EWMA alpha<input id="dynamic-alpha" type="number" min="0.05" max="0.8" step="0.05" value={controls.forecast_alpha} onChange={(e) => setControls({ ...controls, forecast_alpha: e.target.value })} /></label>
            <label htmlFor="dynamic-margin">Fallback margin<input id="dynamic-margin" type="number" min="0" max="1" step="0.05" value={controls.margin_fraction} onChange={(e) => setControls({ ...controls, margin_fraction: e.target.value })} /></label>
            <label htmlFor="dynamic-margin-floor">Fallback floor (GPUs)<input id="dynamic-margin-floor" type="number" min="0" max="256" step="1" value={controls.margin_floor_gpus} onChange={(e) => setControls({ ...controls, margin_floor_gpus: e.target.value })} /></label>
            <label htmlFor="dynamic-floor">Minimum active fleet<input id="dynamic-floor" type="number" min="0" max="1" step="0.05" value={controls.min_active_fraction} onChange={(e) => setControls({ ...controls, min_active_fraction: e.target.value })} /></label>
            <label htmlFor="dynamic-warm-overhead">Warm standby target (nodes)<input id="dynamic-warm-overhead" type="number" min="0" max="8" step="1" value={controls.warm_overhead_nodes} onChange={(e) => setControls({ ...controls, warm_overhead_nodes: e.target.value })} /><small>Default 2 so one can remain while another serves a request; cold replenishment takes 20 min.</small></label>
            <button type="button" className="quiet-button" onClick={() => setControls({ ...controls, nodes: 12, gpus_per_node: 8 })}>96-GPU reference</button>
          </div>
        </details>
      </form>
      {error && <p className="queue-error" role="alert">{error}</p>}
      {result && <div className="dynamic-output">
        <div className="dynamic-status-strip">
          <p className="dynamic-run-summary">Seed {result.seed} <span>·</span> {result.base_nodes} base + {result.headroom_nodes} headroom nodes × {result.gpus_per_node} = {result.fleet_gpus} GPUs <span>·</span> {result.requests_generated} generated requests <span>·</span> {result.traffic_profile_description} <span>·</span> {result.selected_policy} controller</p>
          <p className="dynamic-traffic-note">{result.headroom_description}. Inventory stays fixed for the full replay. Forecast plans active readiness across the next {result.assumptions.readiness_horizon_minutes} minutes; the default target is two warm-ready standby nodes.</p>
          <p className="dynamic-traffic-note">At the realized offered-load peak ({String(Math.floor(result.realized_peak_snapshot.minute / 60)).padStart(2, '0')}:{String(result.realized_peak_snapshot.minute % 60).padStart(2, '0')}, {result.realized_peak_snapshot.offered_gpus} GPUs), forecast state: {result.realized_peak_snapshot.active_nodes} active, {result.realized_peak_snapshot.warm_ready_nodes} warm-ready, {result.realized_peak_snapshot.booting_nodes} booting, {result.realized_peak_snapshot.warming_nodes} warming, {result.realized_peak_snapshot.off_nodes} off. Available warm stock target {result.realized_peak_snapshot.warm_stock_target_nodes}; readiness gap {formatNumber(result.realized_peak_snapshot.readiness_capacity_shortfall_gpus, 1)} GPUs; legacy scalar warm target {result.realized_peak_snapshot.formula_target_warm_nodes} is diagnostic only.</p>
          <p className="dynamic-admission-note">Flexible schedule: <strong>{result.flexible_schedule.admission_status}</strong>{result.flexible_schedule.admission_reason ? ` — ${result.flexible_schedule.admission_reason}` : ` · ${result.flexible_schedule.priority_policy} allocation shared across controllers.`}</p>
        </div>
        <div className="simulation-playback" aria-label="Simulation replay controls">
          <label htmlFor="replay-policy">Controller</label>
          <select id="replay-policy" value={selectedPolicy} onChange={(event) => { setPlaying(false); setMinute(0); setSelectedPolicy(event.target.value); }}>
            {Object.entries(result.policies).filter(([key]) => key !== 'forecast').map(([key, policy]) => <option key={key} value={key}>{policy.label}</option>)}
          </select>
          {selectedReplay?.frames?.length ? <>
            <button type="button" className="quiet-button" onClick={() => setPlaying((value) => !value)}>{playing ? 'Pause' : 'Play'}</button>
            <label htmlFor="replay-speed">Speed</label>
            <select id="replay-speed" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value="1">1×</option><option value="4">4×</option><option value="16">16×</option></select>
            <button type="button" className="quiet-button" onClick={() => { setPlaying(false); setMinute(0); }}>Reset</button>
            <label className="simulation-seek-label" htmlFor="replay-minute">{String(Math.floor(minute / 60)).padStart(2, '0')}:{String(minute % 60).padStart(2, '0')} / 23:59</label>
            <input id="replay-minute" type="range" min="0" max={lastMinute} value={Math.min(minute, lastMinute)} onChange={(event) => { setPlaying(false); setMinute(Number(event.target.value)); }} aria-label="Simulation minute" />
          </> : <span className="control-help">This result does not include minute-by-minute replay data.</span>}
        </div>
        <SavingsReport comparison={result.comparisons?.[selectedPolicy]} baseline={result.unscheduled_baseline} />
        <HourlyGridCosts policy={result.policies?.[selectedPolicy]} selectedPolicy={selectedPolicy} />
        <div className="simulation-workspace">
          <NodePowerView compact replay={selectedReplay} minute={minute} onMinuteChange={setMinute} gpusPerNode={result.gpus_per_node} />
          <LiveTrafficView compact replay={selectedReplay} minute={minute} />
        </div>
        <details className="simulation-data-disclosure">
          <summary>Controller metrics and policy comparison</summary>
          <div className="job-table-wrap"><table className="comparison-table">
          <thead><tr><th>Measure</th>{Object.entries(result.policies).filter(([key]) => key !== 'forecast').map(([key, item]) => <th key={key}>{item.label}</th>)}</tr></thead>
          <tbody>{Object.entries(LABELS).map(([key, [label, unit]]) => <tr key={key}><th scope="row">{label}</th>{Object.entries(result.policies).filter(([key]) => key !== 'forecast').map(([policy, item]) => <td key={policy}>{formatNumber(item.metrics[key], key.includes('fraction') ? 3 : key.includes('minutes') ? 1 : 2)}{unit ? ` ${unit}` : ''}</td>)}</tr>)}</tbody>
          </table></div>
        </details>
        <details className="simulation-data-disclosure">
          <summary>Flexible job commitments · {result.policies.forecast_v2.flexible_admission_status}</summary>
          <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Job</th><th>Tier</th><th>Window</th><th>Planned</th><th>Delivered</th><th>Unmet</th><th>Deadline</th><th>Status</th></tr></thead><tbody>
          {result.policies.forecast_v2.flexible_jobs.map((job) => <tr key={job.id}><td>{job.name}</td><td>{job.tier}</td><td>{job.arrival}:00–{job.deadline}:00</td><td>{formatNumber(job.gpu_hours, 1)} GPU·h</td><td>{formatNumber(job.delivered_gpu_hours, 1)} GPU·h</td><td>{formatNumber(job.unmet_gpu_hours, 1)} GPU·h</td><td>{job.deadline_met ? 'Met' : 'Not met'}</td><td>{job.status}</td></tr>)}
          </tbody></table></div>
        </details>
        <details className="assumptions"><summary>Demand, forecast, hardware, power and pricing assumptions</summary><div className="assumptions-content"><ul>
          <li>{result.assumptions.demand_model}.</li><li>{result.assumptions.forecast}. Class GPU-minutes/request factors: {Object.entries(result.assumptions.forecast_workload_gpu_minutes_per_request).map(([name, value]) => `${name} ${formatNumber(value, 2)}`).join(', ')}. {result.assumptions.forecast_workload_factor_method}. {result.assumptions.forecast_calibration_limit}</li>
          <li>{result.assumptions.node_control}; warm-to-active {result.assumptions.warm_start_minutes} min (idealized instant promotion), cold-to-warm {result.assumptions.cold_to_warm_minutes} min, cold-to-dispatchable total {result.assumptions.cold_to_active_minutes} min. {result.assumptions.wait_aware_readiness_equation} {result.assumptions.legacy_scalar_warm_target} {result.assumptions.warm_overhead} Queued work fills reserve: {result.assumptions.warm_queue_fill_rule} Queue load uses: {result.assumptions.warm_queue_forecast_approximation}.</li>
          <li>{result.assumptions.minimum_active_floor}.</li>
          <li>Power coefficients (kW IT): {Object.entries(result.assumptions.power_kw_it).map(([k, v]) => `${k} ${v}`).join(', ')}; PUE {result.assumptions.pue}. These are illustrative, not measurements.</li>
          <li>{result.assumptions.renewables}. Tariff: {result.assumptions.tariff} (<a href={result.assumptions.tariff_reference_url} target="_blank" rel="noreferrer">official source</a>). Grid factor: {result.assumptions.grid_emissions} (<a href={result.assumptions.grid_emissions_reference_url} target="_blank" rel="noreferrer">official source</a>).</li>
          <li>{result.assumptions.flexible_jobs} Real-time requests have runtime priority; accepted flexible work waits for residual active capacity and catches up within its window when possible. GPU-hours not delivered by each deadline are reported as unmet. No running request is preempted; no SLA is guaranteed.</li>
        </ul><p>Five-minute trace snapshots show offered demand and node readiness. Booting/off/warm/active nodes are distinct; cold nodes do not become active instantly.</p></div></details>
        <details className="simulation-data-disclosure">
          <summary>Five-minute forecast trace</summary>
          <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Minute</th><th>Offered GPUs</th><th>Realtime upper</th><th>Flexible commitments</th><th>Total upper demand</th><th>Target active nodes</th><th>Legacy warm target</th><th>Warm stock target</th><th>Ready warm</th><th>Warm stock pipeline</th><th>Stock deficit</th><th>Readiness gap</th><th>Margin / source</th><th>Running request GPUs</th><th>Running flexible GPUs</th><th>Active</th><th>Warm</th><th>Booting</th><th>Off</th></tr></thead><tbody>
          {(result.policies.forecast_v2.state_trace || []).filter((_, i) => i % 24 === 0).map((row) => <tr key={row.minute}><td>{Math.floor(row.minute / 60)}:{String(row.minute % 60).padStart(2, '0')}</td><td>{row.offered_gpus}</td><td>{formatNumber(row.forecast_upper_gpus, 1)}</td><td>{formatNumber(row.flexible_commitment_gpus, 1)}</td><td>{formatNumber(row.forecast_total_upper_gpus, 1)}</td><td>{row.forecast_target_active_nodes}</td><td>{row.target_warm_nodes} (diagnostic)</td><td>{row.warm_stock_target_nodes}</td><td>{row.warm_reserve_ready_nodes}</td><td>{row.warm_reserve_pipeline_nodes}</td><td>{row.warm_stock_shortfall_nodes}</td><td>{formatNumber(row.readiness_capacity_shortfall_gpus, 1)}</td><td>{formatNumber(row.forecast_margin_gpus, 1)} / {row.forecast_margin_source}</td><td>{row.running_gpus}</td><td>{formatNumber(row.flexible_gpus, 1)}</td><td>{row.active_nodes}</td><td>{row.warm_nodes}</td><td>{row.booting_nodes}</td><td>{row.off_nodes}</td></tr>)}
          </tbody></table></div>
        </details>
      </div>}
      {!result && <div className="simulation-workspace">
        <NodePowerView compact replay={null} minute={0} gpusPerNode={Number(controls.gpus_per_node)} />
        <LiveTrafficView compact replay={null} minute={0} />
      </div>}
    </section>
  );
}
