import { formatNumber } from './Controls.jsx';

function percent(value, suffix = '%') {
  return value === null || value === undefined ? '—' : `${formatNumber(value, 1)}${suffix}`;
}

function Metric({ label, baseline, optimized, change, unit = '', positiveWhenLower = true }) {
  const improved = change !== null && (positiveWhenLower ? change >= 0 : change <= 0);
  const changeText = change === null ? null : `${change > 0 ? '−' : change < 0 ? '+' : ''}${formatNumber(Math.abs(change), 1)}%`;
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{formatNumber(baseline, label.includes('Cost') ? 2 : 1)}{unit}</td>
      <td className="optimized-value">{formatNumber(optimized, label.includes('Cost') ? 2 : 1)}{unit}{changeText && <span className={`metric-change ${improved ? 'is-good' : 'is-neutral'}`}>{changeText}</span>}</td>
    </tr>
  );
}

export function ComparisonTable({ result }) {
  const baseline = result.baseline.metrics;
  const optimized = result.optimized.metrics;
  const comparable = result.comparison.comparable;
  const costChange = comparable ? result.comparison.cost_savings_pct : null;
  const emissionChange = comparable ? result.comparison.emissions_change_pct : null;
  return (
    <div className="comparison-table-wrap">
      <table className="comparison-table">
        <thead><tr><th>Measure</th><th>Priority ASAP</th><th>{result.optimizer.priority_policy_label} LP</th></tr></thead>
        <tbody>
          <Metric label="Grid cost" baseline={baseline.grid_cost_units} optimized={optimized.grid_cost_units} change={costChange} unit=" CU" />
          <Metric label="Grid emissions" baseline={baseline.grid_emissions_kg_co2e} optimized={optimized.grid_emissions_kg_co2e} change={emissionChange} unit=" kgCO₂e" />
          <tr><th scope="row">Facility energy</th><td>{formatNumber(baseline.total_facility_energy_kwh, 1)} kWh</td><td className="optimized-value">{formatNumber(optimized.total_facility_energy_kwh, 1)} kWh</td></tr>
          <tr><th scope="row">Grid imports</th><td>{formatNumber(baseline.grid_import_kwh, 1)} kWh</td><td className="optimized-value">{formatNumber(optimized.grid_import_kwh, 1)} kWh</td></tr>
          <tr>
            <th scope="row">Weighted objective</th>
            <td>{formatNumber(baseline.weighted_objective_units, 2)} CU-eq</td>
            <td className="optimized-value">{formatNumber(optimized.weighted_objective_units, 2)} CU-eq</td>
          </tr>
          <tr>
            <th scope="row">Deadlines met</th>
            <td>{baseline.deadlines_met} / {baseline.deadline_count} <span className="table-subtle">({percent(baseline.deadline_count ? (baseline.deadlines_met / baseline.deadline_count) * 100 : 0)})</span></td>
            <td className="optimized-value">{optimized.deadlines_met} / {optimized.deadline_count} <span className="table-subtle">({percent(optimized.deadline_count ? (optimized.deadlines_met / optimized.deadline_count) * 100 : 0)})</span></td>
          </tr>
          <tr>
            <th scope="row">Flexible work unmet</th>
            <td>{formatNumber(baseline.flexible_gpu_hours_unmet)} GPU-h</td>
            <td className="optimized-value">{formatNumber(optimized.flexible_gpu_hours_unmet)} GPU-h</td>
          </tr>
          <tr>
            <th scope="row">Renewable used</th>
            <td>{formatNumber(result.baseline.metrics.renewable_used_kwh)} kWh</td>
            <td className="optimized-value">{formatNumber(optimized.renewable_used_kwh)} kWh</td>
          </tr>
          <tr>
            <th scope="row">Renewable curtailed</th>
            <td>{formatNumber(baseline.renewable_curtailed_kwh)} kWh</td>
            <td className="optimized-value">{formatNumber(optimized.renewable_curtailed_kwh)} kWh</td>
          </tr>
          <tr><th scope="row">Peak reserved-capacity use</th><td>{formatNumber(baseline.peak_reserved_gpu_utilization, 1)} / {result.case.gpu_count} GPUs</td><td className="optimized-value">{formatNumber(optimized.peak_reserved_gpu_utilization, 1)} / {result.case.gpu_count} GPUs</td></tr>
          <tr><th scope="row">Peak active-equivalent power use</th><td>{formatNumber(baseline.peak_active_equivalent_gpu_power_use, 1)} GPU-equivalents</td><td className="optimized-value">{formatNumber(optimized.peak_active_equivalent_gpu_power_use, 1)} GPU-equivalents</td></tr>
          <tr>
            <th scope="row">Solver status</th>
            <td><span className="neutral-status">Priority-aware ASAP</span></td>
            <td className="optimized-value"><span className="optimal-status">{result.optimizer.status}</span><span className="table-subtle"> · {formatNumber(result.optimizer.solve_time_seconds * 1000, 2)} ms</span></td>
          </tr>
        </tbody>
      </table>
      <p className="comparison-footnote">The selected LP applies its displayed policy; the Priority ASAP baseline keeps the existing Pro-first tier order. Both use the same energy evaluator. Cost and emissions change is (ASAP − LP) ÷ ASAP; negative means the measure increased. Percentages appear only when both methods complete every job and the baseline denominator is nonzero.</p>
    </div>
  );
}

export function InfeasibleState({ result, onRestore }) {
  const baseline = result.baseline.metrics;
  const isInfeasible = result.optimizer.status === 'Infeasible';
  const heading = isInfeasible ? 'Infeasible schedule' : 'No optimized schedule available';
  const lead = isInfeasible
    ? 'The solver found no schedule that satisfies every job deadline and GPU-capacity limit.'
    : 'The optimizer did not return a verified optimal schedule for these inputs.';
  const detail = isInfeasible
    ? 'No optimized schedule or savings comparison is available for these inputs.'
    : result.optimizer.message || 'No optimized results are shown until the solver returns a validated optimal schedule.';
  return (
    <section className={`infeasible-state ${isInfeasible ? '' : 'solver-warning'}`} role="status" aria-live="polite">
      <div className="infeasible-rule" />
      <div className="infeasible-copy">
        <h2>{heading}</h2>
        <p className="infeasible-lead">{lead}</p>
        <p className="infeasible-detail">{detail}</p>
      </div>
      <div className="infeasible-details">
        <div><span>Solver status</span><strong>{result.optimizer.status}</strong></div>
        <div><span>ASAP work delivered</span><strong>{formatNumber(baseline.flexible_gpu_hours_delivered)} GPU-h</strong></div>
        <div><span>ASAP work unmet</span><strong>{formatNumber(baseline.flexible_gpu_hours_unmet)} GPU-h</strong></div>
      </div>
      <button className="restore-button" type="button" onClick={onRestore}>Restore baseline scenario</button>
    </section>
  );
}
