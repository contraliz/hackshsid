import { formatNumber } from './Controls.jsx';

const CHART = { left: 52, right: 940, top: 12, bottom: 214 };
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

function xFor(hour) {
  return CHART.left + (hour / 23) * (CHART.right - CHART.left);
}

function yFor(value, max) {
  return CHART.bottom - (value / max) * (CHART.bottom - CHART.top);
}

function linePath(values, max) {
  return values.map((value, hour) => `${hour === 0 ? 'M' : 'L'} ${xFor(hour).toFixed(2)} ${yFor(value, max).toFixed(2)}`).join(' ');
}

function Axis({ max, unit, suffix = '', tickValues }) {
  const ticks = tickValues ?? [0, max / 3, (max * 2) / 3, max];
  return (
    <g className="chart-axis">
      {ticks.map((tick, index) => {
        const y = yFor(tick, max);
        return <g key={index}><line x1={CHART.left} y1={y} x2={CHART.right} y2={y} className="gridline" /><text x={CHART.left - 10} y={y + 4} textAnchor="end">{formatNumber(tick)}{suffix}</text></g>;
      })}
      <text className="axis-caption" x={CHART.left} y="248">{unit}</text>
      {HOURS.filter((hour) => hour % 4 === 0).map((hour) => <text key={hour} x={xFor(hour)} y="232" textAnchor="middle">{String(hour).padStart(2, '0')}</text>)}
      <text className="axis-caption" x={(CHART.left + CHART.right) / 2} y="266" textAnchor="middle">Hour of day</text>
    </g>
  );
}

export function ComputeChart({ result }) {
  const { case: input, baseline, optimized } = result;
  const baselineGpu = baseline.hourly.total_gpus;
  const optimizedGpu = optimized.hourly.total_gpus;
  const selectedPolicy = result.optimizer.priority_policy_label;
  const max = Math.ceil(input.gpu_count / 4) * 4;
  return (
    <div className="chart-frame compute-chart">
      <div className="chart-legend">
        <span><i className="line-swatch optimized-line" />{selectedPolicy} LP</span>
        <span><i className="line-swatch baseline-line" />Priority ASAP</span>
      </div>
      <svg className="data-chart" viewBox="0 0 960 278" role="img" aria-labelledby="compute-chart-title compute-chart-desc">
        <title id="compute-chart-title">Total GPU use by hour</title>
        <desc id="compute-chart-desc">The chart compares reserved-capacity GPU use for the selected LP policy and a Pro-priority ASAP baseline over 24 hours.</desc>
        <Axis max={max} unit="GPUs" />
        {HOURS.map((hour) => <circle key={`b-${hour}`} cx={xFor(hour)} cy={yFor(baselineGpu[hour], max)} r="2.2" className="baseline-point"><title>{`${String(hour).padStart(2, '0')}:00 · Priority ASAP ${formatNumber(baselineGpu[hour])} GPUs`}</title></circle>)}
        {HOURS.map((hour) => <circle key={`o-${hour}`} cx={xFor(hour)} cy={yFor(optimizedGpu[hour], max)} r="2.6" className="optimized-point"><title>{`${String(hour).padStart(2, '0')}:00 · ${selectedPolicy} LP ${formatNumber(optimizedGpu[hour])} GPUs`}</title></circle>)}
        <path d={linePath(baselineGpu, max)} className="baseline-path" />
        <path d={linePath(optimizedGpu, max)} className="optimized-path" />
      </svg>
    </div>
  );
}

export function EnergyChart({ result }) {
  const input = result.case;
  const methods = [
    { name: 'ASAP baseline', key: 'baseline', data: result.baseline.hourly, className: 'baseline-energy' },
    { name: `${result.optimizer.priority_policy_label} LP`, key: 'optimized', data: result.optimized.hourly, className: 'optimized-energy' },
  ];
  const maxValue = Math.max(...methods.flatMap(({ data }) => data.load_kwh));
  const max = Math.ceil(maxValue / 25) * 25;
  const barWidth = 10;
  return (
    <div className="chart-frame energy-chart">
      <svg className="data-chart" viewBox="0 0 960 278" role="img" aria-labelledby="energy-chart-title energy-chart-desc">
        <title id="energy-chart-title">Hourly facility energy by method</title>
        <desc id="energy-chart-desc">Paired stacked bars compare hourly renewable use and grid imports for the ASAP baseline and optimized schedule.</desc>
        <Axis max={max} unit="kWh per slot" />
        {HOURS.map((hour) => {
          return (
            <g key={hour}>
              {methods.map((method, methodIndex) => {
                const energy = method.data;
                const x = xFor(hour) + (methodIndex === 0 ? -barWidth - 1 : 1);
                const renewHeight = (energy.renewable_used_kwh[hour] / max) * (CHART.bottom - CHART.top);
                const gridHeight = (energy.grid_import_kwh[hour] / max) * (CHART.bottom - CHART.top);
                const renewY = CHART.bottom - renewHeight;
                const gridY = renewY - gridHeight;
                return (
                  <g key={method.key} className={method.className}>
                    <rect x={x} y={gridY} width={barWidth} height={Math.max(0, gridHeight)} className="bar-grid">
                      <title>{`${String(hour).padStart(2, '0')}:00 · ${method.name}: grid ${formatNumber(energy.grid_import_kwh[hour], 1)} kWh, renewable ${formatNumber(energy.renewable_used_kwh[hour], 1)} kWh; available ${formatNumber(input.renewable_available_kwh[hour], 1)} kWh`}</title>
                    </rect>
                    <rect x={x} y={renewY} width={barWidth} height={Math.max(0, renewHeight)} className="bar-renewable" />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const POLICY_SERIES = [
  { key: 'always_on', label: 'Always-on', color: '#2763a5' },
  { key: 'reactive', label: 'Reactive', color: '#c27a16' },
  { key: 'forecast', label: 'Forecast', color: '#7358b8' },
];

const SMALL_CHART = { left: 39, right: 310, top: 12, bottom: 158 };

function smallX(hour) {
  return SMALL_CHART.left + (hour / 23) * (SMALL_CHART.right - SMALL_CHART.left);
}

function smallY(value, max) {
  return SMALL_CHART.bottom - (value / max) * (SMALL_CHART.bottom - SMALL_CHART.top);
}

function smallAxis(max, unit) {
  return (
    <g className="chart-axis">
      {[0, max / 2, max].map((tick, index) => {
        const y = smallY(tick, max);
        return <g key={index}><line x1={SMALL_CHART.left} y1={y} x2={SMALL_CHART.right} y2={y} className="gridline" /><text x={SMALL_CHART.left - 5} y={y + 3} textAnchor="end">{formatNumber(tick, tick % 1 ? 1 : 0)}</text></g>;
      })}
      {[0, 6, 12, 18, 23].map((hour) => <text key={hour} x={smallX(hour)} y="177" textAnchor="middle">{String(hour).padStart(2, '0')}</text>)}
      <text className="axis-caption" x={(SMALL_CHART.left + SMALL_CHART.right) / 2} y="202" textAnchor="middle">Hour</text>
      <text className="axis-caption" transform={`translate(10 ${(SMALL_CHART.top + SMALL_CHART.bottom) / 2}) rotate(-90)`} textAnchor="middle">{unit}</text>
    </g>
  );
}

export function PolicyEnergyMixCharts({ result }) {
  const maxValue = Math.max(0, ...POLICY_SERIES.flatMap(({ key }) =>
    result.policies[key].hourly_energy.map((row) => row.facility_kwh)));
  const max = Math.max(5, Math.ceil(maxValue / 5) * 5);
  const chartHeight = SMALL_CHART.bottom - SMALL_CHART.top;
  const barWidth = 6;
  return (
    <>
      <div className="legend-inline policy-energy-legend" aria-label="Energy sources">
        <span><i className="legend-swatch renewable" />Renewable used</span>
        <span><i className="legend-swatch grid" />Grid imported</span>
      </div>
      <div className="policy-energy-grid">
        {POLICY_SERIES.map(({ key, label }) => (
          <section className="policy-energy-panel" key={key} aria-label={`${label} electricity use by hour`}>
            <h3>{label}</h3>
            <svg className="policy-energy-chart" viewBox="0 0 320 210" role="img" aria-labelledby={`policy-energy-${key}-title policy-energy-${key}-desc`}>
              <title id={`policy-energy-${key}-title`}>{`${label} hourly electricity mix`}</title>
              <desc id={`policy-energy-${key}-desc`}>Stacked hourly bars show renewable electricity used and grid electricity imported, on a shared scale across all three controllers.</desc>
              {smallAxis(max, 'kWh')}
              {result.policies[key].hourly_energy.map((row) => {
                const center = smallX(row.hour);
                const renewableHeight = (row.renewable_kwh / max) * chartHeight;
                const gridHeight = (row.grid_kwh / max) * chartHeight;
                const renewableY = SMALL_CHART.bottom - renewableHeight;
                const gridY = renewableY - gridHeight;
                return <g key={row.hour}>
                  <rect x={center - barWidth / 2} y={gridY} width={barWidth} height={Math.max(0, gridHeight)} className="bar-grid">
                    <title>{`${String(row.hour).padStart(2, '0')}:00 ${label}: ${formatNumber(row.grid_kwh, 2)} kWh grid, ${formatNumber(row.renewable_kwh, 2)} kWh renewable, ${formatNumber(row.facility_kwh, 2)} kWh total`}</title>
                  </rect>
                  <rect x={center - barWidth / 2} y={renewableY} width={barWidth} height={Math.max(0, renewableHeight)} className="bar-renewable">
                    <title>{`${String(row.hour).padStart(2, '0')}:00 ${label}: ${formatNumber(row.renewable_kwh, 2)} kWh renewable used`}</title>
                  </rect>
                </g>;
              })}
            </svg>
            <p>{formatNumber(result.policies[key].metrics.facility_kwh, 1)} kWh facility total</p>
          </section>
        ))}
      </div>
    </>
  );
}

function MultiPolicyLineChart({ result, field, title, description, unit, max, digits = 1, tickValues }) {
  const series = POLICY_SERIES.map(({ key, label, color }) => ({
    key, label, color,
    values: result.policies[key].hourly_energy.map((row) => row[field]),
  }));
  return (
    <div className="chart-frame policy-line-chart">
      <div className="chart-legend" aria-label={`${title} legend`}>
        {series.map((line) => <span key={line.key}><i className="policy-line-swatch" style={{ '--policy-color': line.color }} />{line.label}</span>)}
      </div>
      <svg className="data-chart" viewBox="0 0 960 278" role="img" aria-labelledby={`${field}-chart-title ${field}-chart-desc`}>
        <title id={`${field}-chart-title`}>{title}</title>
        <desc id={`${field}-chart-desc`}>{description}</desc>
        <Axis max={max} unit={unit} tickValues={tickValues} />
        {series.map((line) => <g key={line.key}>
          <path d={linePath(line.values, max)} className="policy-path" style={{ '--policy-color': line.color }} />
          {line.values.map((value, hour) => <circle key={hour} cx={xFor(hour)} cy={yFor(value, max)} r="2.5" className="policy-point" style={{ '--policy-color': line.color }}>
            <title>{`${String(hour).padStart(2, '0')}:00 · ${line.label}: ${formatNumber(value, digits)} ${unit}`}</title>
          </circle>)}
        </g>)}
      </svg>
    </div>
  );
}

export function PolicyEmissionsChart({ result }) {
  const peak = Math.max(0, ...POLICY_SERIES.flatMap(({ key }) =>
    result.policies[key].hourly_energy.map((row) => row.emissions_kg)));
  const max = Math.max(5, Math.ceil(peak / 5) * 5);
  return <MultiPolicyLineChart result={result} field="emissions_kg" title="Hourly grid emissions by controller"
    description="The three lines show hourly grid emissions from the same completed simulation runs, using the simulation's configured carbon-intensity profile."
    unit="kg CO₂" max={max} digits={2} />;
}

export function PolicyCostChart({ result }) {
  const peak = Math.max(0, ...POLICY_SERIES.flatMap(({ key }) =>
    result.policies[key].hourly_energy.map((row) => row.cost_cny)));
  const max = Math.max(0.01, Math.ceil(peak * 100) / 100);
  return <MultiPolicyLineChart result={result} field="cost_cny" title="Hourly grid cost by controller"
    description="Hourly energy costs from the simulation's illustrative CNY tariff. This is a simulation output, not a utility bill."
    unit="CNY" max={max} digits={2} />;
}

export function PolicyQueueChart({ result }) {
  const peak = Math.max(0, ...POLICY_SERIES.flatMap(({ key }) =>
    result.policies[key].hourly_energy.map((row) => row.peak_queued_requests)));
  const max = Math.max(2, Math.ceil(peak / 2) * 2);
  return <MultiPolicyLineChart result={result} field="peak_queued_requests" title="Peak real-time queue by hour"
    description="The three lines compare the highest queued-request count recorded at any simulation minute within each hour."
    unit="queued requests" max={max} digits={0} tickValues={[0, max / 2, max]} />;
}
