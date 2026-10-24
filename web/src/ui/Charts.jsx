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

function Axis({ max, unit, suffix = '' }) {
  const ticks = [0, max / 3, (max * 2) / 3, max];
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
