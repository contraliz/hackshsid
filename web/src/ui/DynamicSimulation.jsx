import { useEffect, useState } from 'react';
import { formatNumber } from './Controls.jsx';
import { LiveTrafficView } from './LiveTrafficView.jsx';

const LABELS = {
  facility_kwh: ['Facility energy', 'kWh'], grid_kwh: ['Grid imports', 'kWh'],
  renewable_used_kwh: ['Renewable used', 'kWh'], renewable_curtailed_kwh: ['Renewable curtailed', 'kWh'],
  cost_cny: ['Illustrative grid cost', 'CNY'], emissions_kg: ['Grid CO₂', 'kg CO₂'],
  requests_completed: ['Completed requests', ''], requests_queued_at_horizon: ['Queued at horizon', ''],
  requests_rejected: ['Rejected requests', ''], mean_wait_minutes: ['Mean queue wait', 'min'],
  p95_wait_minutes: ['P95 queue wait', 'min'], mean_completion_latency_minutes: ['Mean completion latency', 'min'],
  latency_allowance_met: ['Illustrative response allowances met', 'requests'], peak_active_nodes: ['Peak active nodes', ''],
  max_forecast_capacity_shortfall_gpus: ['Peak forecast fleet shortfall', 'GPUs'], forecast_shortfall_minutes: ['Forecast shortfall intervals', '5-min intervals'],
  peak_offered_fleet_shortfall_gpus: ['Peak realized demand above fleet', 'GPUs'], offered_fleet_shortfall_minutes: ['Realized fleet overload', 'min'],
  flexible_jobs_admitted: ['Flexible jobs admitted', 'jobs'], flexible_jobs_deadline_met: ['Flexible deadlines met', 'jobs'],
  flexible_gpu_hours_scheduled: ['Flexible work scheduled', 'GPU·h'], flexible_gpu_hours_delivered: ['Flexible work delivered', 'GPU·h'],
  flexible_gpu_hours_unmet: ['Flexible work unmet / not admitted', 'GPU·h'], flexible_commitment_missed_gpu_minutes: ['Flexible commitment shortfall', 'GPU·min'],
};

export function DynamicSimulation() {
  const [controls, setControls] = useState({ nodes: 32, gpus_per_node: 8, seed: 2026, forecast_alpha: 0.3, margin_fraction: 0.15, min_active_fraction: 0.25, bursts: true });
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedPolicy, setSelectedPolicy] = useState('forecast');
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
        body: JSON.stringify({ ...controls, nodes: Number(controls.nodes), gpus_per_node: Number(controls.gpus_per_node), seed: Number(controls.seed), forecast_alpha: Number(controls.forecast_alpha), margin_fraction: Number(controls.margin_fraction), min_active_fraction: Number(controls.min_active_fraction) }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
      setResult(body);
      setSelectedPolicy(body.selected_policy && body.policies?.[body.selected_policy] ? body.selected_policy : 'forecast');
      setMinute(0);
    } catch (e) { setError(e.message || 'Simulation failed.'); }
    finally { setBusy(false); }
  }

  return (
    <section className="chart-section" aria-labelledby="dynamic-title">
      <div className="section-title-row"><div><h2 id="dynamic-title">Node power-state simulation</h2><p className="section-unit">Identical seeded request trace · always-on vs reactive vs forecast reserve</p></div></div>
      <form className="dynamic-controls" onSubmit={run}>
        <label>Nodes<input type="number" min="2" max="64" value={controls.nodes} onChange={(e) => setControls({ ...controls, nodes: e.target.value })} /></label>
        <label>GPUs per node<input type="number" min="1" max="16" value={controls.gpus_per_node} onChange={(e) => setControls({ ...controls, gpus_per_node: e.target.value })} /></label>
        <label>Traffic seed<input type="number" min="0" value={controls.seed} onChange={(e) => { setPlaying(false); setMinute(0); setControls({ ...controls, seed: e.target.value }); }} /></label>
        <label>EWMA alpha<input type="number" min="0.05" max="0.8" step="0.05" value={controls.forecast_alpha} onChange={(e) => setControls({ ...controls, forecast_alpha: e.target.value })} /></label>
        <label>Fallback margin<input type="number" min="0" max="1" step="0.05" value={controls.margin_fraction} onChange={(e) => setControls({ ...controls, margin_fraction: e.target.value })} /></label>
        <label>Minimum active fleet<input type="number" min="0" max="1" step="0.05" value={controls.min_active_fraction} onChange={(e) => setControls({ ...controls, min_active_fraction: e.target.value })} /></label>
        <button type="button" className="quiet-button" onClick={() => setControls({ ...controls, nodes: 12, gpus_per_node: 8 })}>Illustrative 96-GPU reference</button>
        <label className="dynamic-checkbox"><input type="checkbox" checked={controls.bursts} onChange={(e) => setControls({ ...controls, bursts: e.target.checked })} /> Include seeded burst chance</label>
        <button className="run-button" disabled={busy}>{busy ? 'Simulating…' : 'Run node simulation'}</button>
      </form>
      {error && <p className="queue-error" role="alert">{error}</p>}
      {result && <div className="dynamic-output" aria-live="polite">
        <p className="control-help">Seed {result.seed} · {result.nodes} × {result.gpus_per_node} = {result.fleet_gpus} installed GPUs · {result.requests_generated} generated requests · offered peak {result.offered_peak_gpus} GPUs · selected policy: {result.selected_policy}. Results are synthetic.</p>
        <p className="control-help">Flexible schedule admission: <strong>{result.flexible_schedule.admission_status}</strong>{result.flexible_schedule.admission_reason ? ` — ${result.flexible_schedule.admission_reason}` : ` — ${result.flexible_schedule.priority_policy} LP schedule is shared across all three node policies. Fixed real-time reservations constrain LP admission; generated requests replace that reservation in minute energy accounting.`}</p>
        <div className="simulation-playback" aria-label="Simulation replay controls">
          <label htmlFor="replay-policy">Controller</label>
          <select id="replay-policy" value={selectedPolicy} onChange={(event) => { setPlaying(false); setMinute(0); setSelectedPolicy(event.target.value); }}>
            {Object.entries(result.policies).map(([key, policy]) => <option key={key} value={key}>{policy.label}</option>)}
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
        {selectedReplay && <>
          <LiveTrafficView replay={selectedReplay} minute={minute} />
          {/* Node power visualization integration point: <NodePowerView replay={selectedReplay} minute={minute} onMinuteChange={setMinute} gpusPerNode={result.gpus_per_node} /> */}
        </>}
        <div className="job-table-wrap"><table className="comparison-table">
          <thead><tr><th>Measure</th>{Object.entries(result.policies).map(([key, item]) => <th key={key}>{item.label}</th>)}</tr></thead>
          <tbody>{Object.entries(LABELS).map(([key, [label, unit]]) => <tr key={key}><th scope="row">{label}</th>{Object.entries(result.policies).map(([policy, item]) => <td key={policy}>{formatNumber(item.metrics[key], key.includes('fraction') ? 3 : key.includes('minutes') ? 1 : 2)}{unit ? ` ${unit}` : ''}</td>)}</tr>)}</tbody>
        </table></div>
        <h3>Flexible job commitments — {result.policies.forecast.flexible_admission_status}</h3>
        <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Job</th><th>Tier</th><th>Window</th><th>Planned</th><th>Delivered</th><th>Unmet</th><th>Deadline</th><th>Status</th></tr></thead><tbody>
          {result.policies.forecast.flexible_jobs.map((job) => <tr key={job.id}><td>{job.name}</td><td>{job.tier}</td><td>{job.arrival}:00–{job.deadline}:00</td><td>{formatNumber(job.gpu_hours, 1)} GPU·h</td><td>{formatNumber(job.delivered_gpu_hours, 1)} GPU·h</td><td>{formatNumber(job.unmet_gpu_hours, 1)} GPU·h</td><td>{job.deadline_met ? 'Met' : 'Not met'}</td><td>{job.status}</td></tr>)}
        </tbody></table></div>
        <details className="assumptions"><summary>Demand, forecast, hardware, power and pricing assumptions</summary><div className="assumptions-content"><ul>
          <li>{result.assumptions.demand_model}.</li><li>{result.assumptions.forecast}. {result.assumptions.forecast_calibration_limit}.</li>
          <li>{result.assumptions.node_control}; warm-to-active {result.assumptions.warm_start_minutes} min and cold-to-warm {result.assumptions.cold_to_warm_minutes} min.</li>
          <li>{result.assumptions.minimum_active_floor}.</li>
          <li>Power coefficients (kW IT): {Object.entries(result.assumptions.power_kw_it).map(([k, v]) => `${k} ${v}`).join(', ')}; PUE {result.assumptions.pue}. These are illustrative, not measurements.</li>
          <li>{result.assumptions.renewables}. Tariff: {result.assumptions.tariff} (<a href={result.assumptions.tariff_reference_url} target="_blank" rel="noreferrer">official source</a>). Grid factor: {result.assumptions.grid_emissions} (<a href={result.assumptions.grid_emissions_reference_url} target="_blank" rel="noreferrer">official source</a>).</li>
          <li>{result.assumptions.flexible_jobs} Accepted flexible jobs follow a fixed hourly LP allocation with no runtime preemption or rescheduling. GPU-hours not delivered by each deadline are reported as unmet. Requests with response allowance shorter than startup remain exposed until active spare capacity exists; no SLA guarantee.</li>
        </ul><p>Five-minute trace snapshots show offered demand and node readiness. Booting/off/warm/active nodes are distinct; cold nodes do not become active instantly.</p></div></details>
        <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Minute</th><th>Offered GPUs</th><th>Realtime upper</th><th>Flexible commitments</th><th>Total upper demand</th><th>Target warm nodes</th><th>Running request GPUs</th><th>Running flexible GPUs</th><th>Active</th><th>Warm</th><th>Booting</th><th>Off</th></tr></thead><tbody>
          {(result.policies.forecast.state_trace || []).filter((_, i) => i % 24 === 0).map((row) => <tr key={row.minute}><td>{Math.floor(row.minute / 60)}:{String(row.minute % 60).padStart(2, '0')}</td><td>{row.offered_gpus}</td><td>{formatNumber(row.forecast_upper_gpus, 1)}</td><td>{formatNumber(row.flexible_commitment_gpus, 1)}</td><td>{formatNumber(row.forecast_total_upper_gpus, 1)}</td><td>{row.target_warm_nodes}</td><td>{row.running_gpus}</td><td>{formatNumber(row.flexible_gpus, 1)}</td><td>{row.active_nodes}</td><td>{row.warm_nodes}</td><td>{row.booting_nodes}</td><td>{row.off_nodes}</td></tr>)}
        </tbody></table></div>
      </div>}
    </section>
  );
}
