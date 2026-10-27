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

function quantity(metrics, key, unit) {
  const value = metrics?.[key];
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
    ? '—'
    : `${number(value, 1)} ${unit}`;
}

function metricChange(pct) {
  if (pct === null || pct === undefined || pct === '' || !Number.isFinite(Number(pct))) {
    return { text: 'Unavailable', kind: 'unavailable' };
  }
  const value = Number(pct);
  if (value < 0) return { text: `${number(Math.abs(value), 1)}% increase`, kind: 'increase' };
  return { text: `${number(value, 1)}% ${value === 0 ? 'change' : 'lower'}`, kind: value === 0 ? 'neutral' : 'reduction' };
}

export function SavingsReport({ comparison, baseline }) {
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
  const waitedCount = Number(optimizedMetrics?.requests_waited) || 0;
  const totalRequests = Number(optimizedMetrics?.requests_total) || 0;
  const waitedShare = totalRequests > 0 ? Math.round((waitedCount / totalRequests) * 100) : 0;
  const hasServiceComparison = comparable === true || comparable === false;

  return <section className="savings-report" aria-labelledby="savings-report-title">
    <div className="savings-report-heading">
      <h2 id="savings-report-title">Savings vs. {baselineLabel}</h2>
      <span>{optimizedLabel} · full-day totals · synthetic estimates</span>
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

    <div className="savings-queue-block">
      <div className="savings-queue-heading">
        <h3>Queue</h3>
        <span>{optimizedLabel} · observed during the replay</span>
      </div>
      <div className="savings-metric-row savings-queue-row">
        <article className="savings-metric">
          <div className="savings-metric-top"><span>Requests that waited</span><strong>{number(waitedCount, 0)}</strong></div>
          <p className="savings-values"><span>{waitedShare}% of {number(totalRequests, 0)} requests waited at least one minute</span></p>
        </article>
      </div>
    </div>

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
