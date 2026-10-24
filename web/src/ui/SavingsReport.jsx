import './SavingsReport.css';

const HEADLINE_METRICS = [
  { key: 'electricity_pct', metric: 'facility_kwh', label: 'Facility electricity', unit: 'kWh', reduction: 'savings' },
  { key: 'grid_import_pct', metric: 'grid_kwh', label: 'Grid import', unit: 'kWh', reduction: 'reduction' },
  { key: 'cost_pct', metric: 'cost_cny', label: 'Illustrative grid cost', unit: 'CNY', reduction: 'reduction' },
  { key: 'emissions_pct', metric: 'emissions_kg', label: 'Grid emissions', unit: 'kg CO₂', reduction: 'reduction' },
];

const SERVICE_METRICS = [
  ['requests_completed', 'Completed requests', ''],
  ['requests_rejected', 'Rejected requests', ''],
  ['requests_queued_at_horizon', 'Queued at day end', ''],
  ['requests_running_at_horizon', 'Running at day end', ''],
  ['mean_wait_minutes', 'Mean queue wait', 'min'],
  ['p95_wait_minutes', 'P95 queue wait', 'min'],
  ['mean_completion_latency_minutes', 'Mean completion latency', 'min'],
  ['flexible_gpu_hours_delivered', 'Flexible work delivered', 'GPU·h'],
  ['flexible_gpu_hours_unmet', 'Flexible work unmet', 'GPU·h'],
  ['flexible_jobs_deadline_met', 'Flexible deadlines met', 'jobs'],
];

function number(value, digits = 1) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function quantity(metrics, key, unit, digits = 1) {
  const value = metrics?.[key];
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
    ? '—'
    : `${number(value, digits)}${unit ? ` ${unit}` : ''}`;
}

function metricChange(pct) {
  if (pct === null || pct === undefined || pct === '' || !Number.isFinite(Number(pct))) {
    return { text: 'Unavailable', kind: 'unavailable' };
  }
  const value = Number(pct);
  if (value < 0) return { text: `${number(Math.abs(value), 1)}% increase`, kind: 'increase' };
  return { text: `${number(value, 1)}% ${value === 0 ? 'change' : 'lower'}`, kind: value === 0 ? 'neutral' : 'reduction' };
}

export function SavingsReport({ comparison, baseline, objectiveAnalysis, selectedPolicy }) {
  if (!comparison) {
    return <section className="savings-report" aria-label="Unscheduled baseline comparison">
      <div className="savings-report-heading"><h2>Vs. unscheduled baseline</h2><span>Full simulated day</span></div>
      <p className="savings-report-empty" role="status">Savings comparison unavailable from this API response. Run this with a backend that provides unscheduled baseline comparisons.</p>
    </section>;
  }

  const { baseline: baselineResult, optimized } = comparison;
  const baselineMetrics = baselineResult?.metrics ?? baseline?.metrics;
  const optimizedMetrics = optimized?.metrics;
  const baselineLabel = baselineResult?.label ?? baseline?.label ?? 'Unscheduled baseline';
  const optimizedLabel = optimized?.label ?? 'Selected controller';
  const comparable = comparison.service_comparable;
  const hasServiceComparison = comparable === true || comparable === false;
  const selectedCandidate = objectiveAnalysis?.candidates?.[selectedPolicy];
  const candidateKeys = objectiveAnalysis?.candidate_order || [];
  const candidateLabels = objectiveAnalysis?.candidates || {};
  const objectiveDefinitions = [
    ['facility_kwh', 'Facility electricity', 'kWh'],
    ['cost_cny', 'Grid cost', 'CNY'],
    ['emissions_kg', 'Operational grid emissions', 'kg CO₂'],
  ];
  const paretoLabel = selectedCandidate?.status === 'pareto_frontier'
    ? 'Pareto candidate · frontier of these simulated alternatives'
    : selectedCandidate?.status === 'dominated'
      ? 'Dominated among service-comparable simulated alternatives'
      : selectedCandidate?.status === 'service_ineligible'
        ? 'Excluded from frontier · service outcomes differ'
        : objectiveAnalysis?.status === 'no_comparable_candidates'
          ? 'No service-comparable candidates for a frontier'
          : 'Three-objective frontier unavailable';

  return <section className="savings-report" aria-labelledby="savings-report-title">
    <div className="savings-report-heading">
      <h2 id="savings-report-title">Savings vs. {baselineLabel}</h2>
      <span>{optimizedLabel} · full-day totals · synthetic estimates</span>
    </div>
    <div className={`pareto-status is-${selectedCandidate?.status || objectiveAnalysis?.status || 'unavailable'}`} role="status">
      <strong>{paretoLabel}</strong>
      {selectedCandidate?.individual_minima && <span>{objectiveDefinitions.filter(([key]) => selectedCandidate.individual_minima[key]).map(([, label]) => `lowest ${label}`).join(' · ') || 'No individual minimum'}</span>}
      <small>Objectives: facility kWh, cost CNY, and grid kg CO₂; no cross-unit weights.</small>
    </div>

    <div className="savings-metric-row">
      {HEADLINE_METRICS.map(({ key, metric, label, unit }) => {
        const change = metricChange(comparison.savings?.[key]);
        return <article className="savings-metric" key={key}>
          <div className="savings-metric-top"><span>{label}</span><strong className={`savings-change is-${change.kind}`}>{change.text}</strong></div>
          <p className="savings-values" title={`${baselineLabel} → ${optimizedLabel}`}>
            <span>{quantity(baselineMetrics, metric, unit)} → {quantity(optimizedMetrics, metric, unit)}</span>
          </p>
          {change.kind === 'unavailable' && comparison.savings_reason?.[key] && <small className="savings-reason">{comparison.savings_reason[key]}</small>}
        </article>;
      })}
    </div>

    <details className="pareto-details">
      <summary>Compare simulated objective candidates · {objectiveAnalysis?.status === 'available' ? 'frontier available' : objectiveAnalysis?.status || 'unavailable'}</summary>
      {!objectiveAnalysis?.candidates && <p className="savings-report-empty" role="status">Pareto analysis is unavailable from this API response.</p>}
      {objectiveAnalysis?.candidates && <>
        <p className="pareto-note">{objectiveAnalysis.scope === 'simulated_candidates_same_trace_not_global_optimum' ? 'This is the non-dominated frontier among this run’s identical-trace candidates, not a global solver optimum.' : 'Candidate analysis is limited to the candidates returned by this API.'} Facility electricity includes site overhead/PUE; grid imports are a separate quantity. The API tolerance is {objectiveAnalysis.tolerance?.absolute ?? '—'} absolute and {objectiveAnalysis.tolerance?.relative ?? '—'} relative.</p>
        <div className="savings-service-table-wrap">
          <table className="pareto-table">
            <thead><tr><th scope="col">Candidate</th><th scope="col">Eligibility / status</th>{objectiveDefinitions.map(([, label, unit]) => <th key={label} scope="col">{label} ({unit})</th>)}<th scope="col">Individual minimum</th></tr></thead>
            <tbody>{candidateKeys.map((key) => {
              const candidate = candidateLabels[key];
              if (!candidate) return null;
              const minima = candidate.individual_minima || {};
              return <tr key={key}>
                <th scope="row">{candidate.label}</th>
                <td>{candidate.status === 'pareto_frontier' ? 'Pareto frontier' : candidate.status === 'dominated' ? 'Dominated' : 'Service-ineligible'}</td>
                {objectiveDefinitions.map(([metric]) => <td key={metric}>{quantity(candidate.metrics, metric, '', 3)}</td>)}
                <td>{objectiveDefinitions.filter(([metric]) => minima[metric]).map(([, label]) => label).join(', ') || '—'}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        {objectiveAnalysis.service_ineligible_candidates?.length > 0 && <p className="pareto-note">Excluded for service outcome differences: {objectiveAnalysis.service_ineligible_candidates.map((key) => candidateLabels[key]?.label || key).join(', ')}.</p>}
      </>}
    </details>

    <details className="savings-service-details">
      <summary>{comparable ? 'Service outcomes match · inspect latency and delivery differences' : 'Service outcomes differ · review before comparing savings'}</summary>
      {!hasServiceComparison && <p className="savings-report-empty" role="status">Service comparability is not provided by this API response.</p>}
      {hasServiceComparison && <>
        {!comparable && <p className="savings-service-note" role="note">{comparison.service_note || 'The baseline and optimized run did not deliver comparable service.'} Savings are shown as energy/cost/emissions totals and do not imply equal service.</p>}
        {comparable && comparison.service_note && <p className="savings-service-note" role="note">{comparison.service_note}</p>}
        <div className="savings-service-table-wrap">
          <table className="savings-service-table">
            <thead><tr><th scope="col">Service measure</th><th scope="col">{baselineLabel}</th><th scope="col">{optimizedLabel}</th></tr></thead>
            <tbody>{SERVICE_METRICS.map(([key, label, unit]) => <tr key={key}>
              <th scope="row">{label}</th>
              <td>{quantity(baselineMetrics, key, unit || 'requests')}</td>
              <td>{quantity(optimizedMetrics, key, unit || 'requests')}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>}
    </details>
  </section>;
}
