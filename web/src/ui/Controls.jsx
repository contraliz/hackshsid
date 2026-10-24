export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(Number(value));
}

export function formatUnits(value, digits = 1) {
  return formatNumber(value, digits);
}

function RangeControl({ id, label, value, min, max, step, unit, onChange, help }) {
  const percent = ((value - min) / (max - min)) * 100;
  return (
    <div className="control-group range-group">
      <div className="control-label-row">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{formatNumber(value, step < 1 ? 2 : 0)}{unit}</output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ '--range-progress': `${percent}%` }}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-describedby={`${id}-help`}
      />
      <div className="range-endpoints" aria-hidden="true"><span>{min}{unit}</span><span>{max}{unit}</span></div>
      <p className="control-help" id={`${id}-help`}>{help}</p>
    </div>
  );
}

export function ScenarioControls({ controls, scenarios, onChange, onRun, busy }) {
  return (
    <form className="controls-form" onSubmit={(event) => { event.preventDefault(); onRun(); }}>
      <div className="control-group">
        <label htmlFor="scenario">Scenario</label>
        <select id="scenario" value={controls.scenario} onChange={(event) => onChange('scenario', event.target.value)}>
          {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.label}</option>)}
        </select>
      </div>

      <div className="control-group">
        <label htmlFor="priority-policy">Optimizer policy</label>
        <select id="priority-policy" value={controls.priority_policy} onChange={(event) => onChange('priority_policy', event.target.value)}>
          <option value="pro_priority">Pro-priority (default)</option>
          <option value="energy_only">Energy-only diagnostic</option>
        </select>
        <p className="control-help">Both policies are solved on the same input for comparison. This selection controls the main schedule shown below.</p>
      </div>

      <div className="control-group">
        <div className="control-label-row">
          <label htmlFor="gpu-count">Total GPUs</label>
          <output htmlFor="gpu-count">{formatNumber(controls.gpu_count)}</output>
        </div>
        <input
          id="gpu-count"
          className="number-input"
          type="number"
          inputMode="numeric"
          min="100"
          max="512"
          step="1"
          value={controls.gpu_count}
          onChange={(event) => onChange('gpu_count', event.target.value)}
          onBlur={(event) => onChange('gpu_count', Math.min(512, Math.max(100, Number(event.target.value) || 100)))}
          aria-describedby="gpu-count-help"
        />
        <p className="control-help" id="gpu-count-help">Capacity shared by real-time and flexible work.</p>
      </div>

      <RangeControl
        id="carbon-weight"
        label="Carbon weight"
        value={controls.carbon_weight}
        min={0}
        max={0.8}
        step={0.05}
        unit=""
        onChange={(value) => onChange('carbon_weight', value)}
        help="λ in CU per kgCO₂e; 0 minimizes grid cost alone."
      />

      <details className="advanced-controls">
        <summary>
          <span>Scenario adjustments</span>
          <svg className="chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 6 4.5 4 4.5-4" /></svg>
        </summary>
        <div className="advanced-controls-body">
          <RangeControl
            id="active-equivalent-fraction"
            label="Active-equivalent real-time GPUs"
            value={controls.realtime_active_equivalent_fraction}
            min={0}
            max={1}
            step={0.1}
            unit="× reserved"
            onChange={(value) => onChange('realtime_active_equivalent_fraction', value)}
            help="Energy-accounting assumption only. Capacity stays at the full reservation. 1.0 preserves the prior default; this is not telemetry."
          />
          <RangeControl
            id="renewable-scale"
            label="Renewable supply"
            value={controls.renewable_scale}
            min={0}
            max={1.5}
            step={0.05}
            unit="×"
            onChange={(value) => onChange('renewable_scale', value)}
            help="Scale the synthetic hourly renewable profile."
          />
          <RangeControl
            id="demand-scale"
            label="Flexible-work scale"
            value={controls.demand_scale}
            min={0.5}
            max={2.5}
            step={0.05}
            unit="×"
            onChange={(value) => onChange('demand_scale', value)}
            help="Scale every flexible job's required GPU-hours."
          />
        </div>
      </details>

      <button className="run-button" type="submit" disabled={busy}>
        {busy ? <><span className="button-spinner" aria-hidden="true" />Solving…</> : 'Run schedule'}
      </button>
    </form>
  );
}
