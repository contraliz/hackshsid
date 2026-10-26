import { useMemo, useState } from 'react';
import './NodePowerView.css';

const STATES = [
  { id: 'active', label: 'Active', legendLabel: 'Active (busy or idle)', color: '#1677f2' },
  { id: 'warm', label: 'Warm standby', legendLabel: 'Warm standby (ready to promote now)', color: '#45a87a' },
  { id: 'warming', label: 'Warming', legendLabel: 'Warming (not ready)', color: '#e0a12e' },
  { id: 'booting', label: 'Booting', legendLabel: 'Booting (not ready)', color: '#b184d3' },
  { id: 'off', label: 'Powered off', legendLabel: 'Off (not ready)', color: '#d8dee8' },
];
const STATE_COLORS = Object.fromEntries(STATES.map(({ id, color }) => [id, color]));
const CHART_WIDTH = 1200;
const LABEL_WIDTH = 116;
const ROW_HEIGHT = 14;
const TOP = 8;

function clockLabel(minute) {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
}

function scrollPanelWithKeyboard(event) {
  const panel = event.currentTarget;
  const maxScroll = panel.scrollHeight - panel.clientHeight;
  if (maxScroll <= 0) return;
  const movement = event.key === 'PageDown' ? panel.clientHeight
    : event.key === 'PageUp' ? -panel.clientHeight
      : event.key === 'ArrowDown' ? 40
        : event.key === 'ArrowUp' ? -40
          : event.key === 'End' ? maxScroll
            : event.key === 'Home' ? -maxScroll : null;
  if (movement === null) return;
  event.preventDefault();
  panel.scrollTop = event.key === 'End' ? maxScroll : event.key === 'Home' ? 0 : Math.max(0, Math.min(maxScroll, panel.scrollTop + movement));
}

function number(value, digits = 2) {
  return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }) : '—';
}

function usableReplay(replay) {
  if (!replay || !Array.isArray(replay.node_ids) || !Array.isArray(replay.frames)) return false;
  if (!replay.node_ids.length || !replay.frames.length) return false;
  return replay.frames.every((frame) => frame
    && Number.isFinite(frame.minute)
    && Array.isArray(frame.states)
    && Array.isArray(frame.used_gpus)
    && Array.isArray(frame.power_kw)
    && frame.states.length === replay.node_ids.length
    && frame.used_gpus.length === replay.node_ids.length
    && frame.power_kw.length === replay.node_ids.length);
}

function buildSegments(nodeIds, frames) {
  const segments = [];
  nodeIds.forEach((nodeId, nodeIndex) => {
    let start = 0;
    let state = frames[0].states[nodeIndex];
    for (let index = 1; index <= frames.length; index += 1) {
      const nextState = index < frames.length ? frames[index].states[nodeIndex] : null;
      if (nextState !== state) {
        segments.push({ nodeId, nodeIndex, start, end: index, state });
        start = index;
        state = nextState;
      }
    }
  });
  return segments;
}

/** Shows observed per-node state and power from a dynamic-simulation replay. */
export function NodePowerView({ replay, minute = 0, onMinuteChange = () => {}, gpusPerNode = 0, compact = false }) {
  const [compactView, setCompactView] = useState('timeline');
  const valid = usableReplay(replay);
  const nodeIds = valid ? replay.node_ids : [];
  const frames = valid ? replay.frames : [];
  const segments = useMemo(() => (valid ? buildSegments(nodeIds, frames) : []), [valid, nodeIds, frames]);
  const requestedMinute = Number.isFinite(Number(minute)) ? Number(minute) : 0;
  const minuteIndex = valid
    ? Math.max(0, Math.min(frames.length - 1, frames.findIndex((frame) => frame.minute >= requestedMinute) === -1
      ? frames.length - 1
      : frames.findIndex((frame) => frame.minute >= requestedMinute)))
    : 0;
  const frame = valid ? frames[minuteIndex] : null;
  const totalPower = frame ? frame.power_kw.reduce((sum, value) => sum + (Number(value) || 0), 0) : 0;
  const totalUsed = frame ? frame.used_gpus.reduce((sum, value) => sum + (Number(value) || 0), 0) : 0;
  const hasWorkloadBreakdown = Array.isArray(frame?.realtime_used_gpus) && Array.isArray(frame?.flexible_used_gpus)
    && frame.realtime_used_gpus.length === nodeIds.length && frame.flexible_used_gpus.length === nodeIds.length;
  const totalRealtimeUsed = hasWorkloadBreakdown ? frame.realtime_used_gpus.reduce((sum, value) => sum + (Number(value) || 0), 0) : 0;
  const totalFlexibleUsed = hasWorkloadBreakdown ? frame.flexible_used_gpus.reduce((sum, value) => sum + (Number(value) || 0), 0) : 0;
  const stateCount = (state) => frame ? frame.states.filter((value) => value === state).length : 0;
  const activeNodeCount = stateCount('active');
  const warmNodeCount = stateCount('warm');
  const warmingNodeCount = stateCount('warming');
  const bootingNodeCount = stateCount('booting');
  const offNodeCount = stateCount('off');
  const activeCapacity = frame && Number.isFinite(frame.active_capacity_gpus)
    ? frame.active_capacity_gpus
    : gpusPerNode > 0 ? activeNodeCount * gpusPerNode : null;
  const activeSpare = frame && Number.isFinite(frame.active_spare_gpus)
    ? frame.active_spare_gpus
    : activeCapacity === null ? null : Math.max(0, activeCapacity - totalUsed);
  const hasRequestTimeline = Array.isArray(replay?.requests) && replay.requests.every((request) => Number.isFinite(request.arrival_minute));
  const waitingNow = hasRequestTimeline ? replay.requests.filter((request) => request.arrival_minute <= frame.minute
    && (request.started_at_minute == null || request.started_at_minute > frame.minute)
    && (request.rejected_at_minute == null || request.rejected_at_minute > frame.minute)).length : null;
  const rowHeight = compact ? 12 : ROW_HEIGHT;
  const chartHeight = TOP * 2 + nodeIds.length * rowHeight + 23;
  const plotWidth = CHART_WIDTH - LABEL_WIDTH;

  if (!replay) {
    return <section className="node-power-view" aria-labelledby="node-power-title">
      <div className="node-power-heading"><div><h3 id="node-power-title">Node power by minute</h3><p>Per-node history appears after a simulation produces a replay.</p></div></div>
      <p className="node-power-empty">Run the node simulation to inspect each node’s observed power state and IT draw.</p>
    </section>;
  }

  if (!valid) {
    return <section className="node-power-view" aria-labelledby="node-power-title">
      <div className="node-power-heading"><div><h3 id="node-power-title">Node power by minute</h3><p>Per-node history is unavailable.</p></div></div>
      <p className="node-power-empty" role="status">This result does not include a compatible per-node replay. Run a newer simulation to see node-level history.</p>
    </section>;
  }

  function selectIndex(index) {
    const bounded = Math.max(0, Math.min(frames.length - 1, index));
    onMinuteChange(frames[bounded].minute);
  }

  function selectChartPosition(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const chartX = ((event.clientX - rect.left) / rect.width) * CHART_WIDTH;
    const ratio = Math.max(0, Math.min(1, (chartX - LABEL_WIDTH) / plotWidth));
    selectIndex(Math.round(ratio * (frames.length - 1)));
  }

  return <section className={`node-power-view${compact ? ' is-compact' : ''}`} aria-labelledby="node-power-title" tabIndex={compact ? 0 : undefined} onKeyDown={scrollPanelWithKeyboard}>
    <div className="node-power-heading">
      <div><h3 id="node-power-title">Node power states</h3><p>{compact ? `Full-day state timeline for all ${nodeIds.length} nodes · click the graph to inspect a minute.` : 'Observed node states across the simulation; select a minute to inspect power and GPU occupancy.'}</p></div>
      <div className="node-power-total" aria-live="polite"><span>Node IT draw</span><strong>{number(totalPower)} kW</strong></div>
    </div>

    {compact && <div className="node-power-view-tabs" role="group" aria-label="Node information view">
      <button type="button" aria-pressed={compactView === 'timeline'} className={compactView === 'timeline' ? 'is-selected' : ''} onClick={() => setCompactView('timeline')}>State timeline</button>
      <button type="button" aria-pressed={compactView === 'nodes'} className={compactView === 'nodes' ? 'is-selected' : ''} onClick={() => setCompactView('nodes')}>Node details</button>
    </div>}

    {(!compact || compactView === 'timeline') && <div className="node-power-legend" aria-label="Node state legend">
      {STATES.map((state) => <span key={state.id}><i className={`node-state-dot state-${state.id}`} aria-hidden="true" />{state.legendLabel}</span>)}
    </div>}

    {(!compact || compactView === 'timeline') && <div className="node-power-chart-wrap" aria-label="Full-day node state timeline" style={compact ? { height: `${chartHeight}px` } : undefined}>
      <svg className="node-power-chart" width={CHART_WIDTH} height={chartHeight} style={{ height: `${chartHeight}px` }} viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`} preserveAspectRatio="none" role="img" aria-labelledby="node-power-chart-title node-power-chart-description" onClick={selectChartPosition}>
        <title id="node-power-chart-title">Power state history for {nodeIds.length} nodes over {frames.length} minutes</title>
        <desc id="node-power-chart-description">Each row represents one node's power state. Blue means active and includes both busy and idle capacity; the selected-minute summary shows idle active GPUs. Green is warm standby and can be promoted immediately in this model. Purple booting and gray off cannot run work yet. Use the replay minute control to inspect ready capacity and work.</desc>
        {nodeIds.map((nodeId, index) => <g key={nodeId}>
          <text className="node-power-row-label" x={LABEL_WIDTH - 9} y={TOP + index * rowHeight + (compact ? 7 : 10)} textAnchor="end">{nodeId}</text>
          <rect x={LABEL_WIDTH} y={TOP + index * rowHeight} width={plotWidth} height={rowHeight - 1} rx="2" fill="#f1f4f8" />
        </g>)}
        {segments.map((segment) => <rect
          key={`${segment.nodeId}-${segment.start}`}
          x={LABEL_WIDTH + (segment.start / frames.length) * plotWidth}
          y={TOP + segment.nodeIndex * rowHeight}
          width={Math.max(0.65, ((segment.end - segment.start) / frames.length) * plotWidth)}
          height={rowHeight - 1}
          rx="1"
          fill={STATE_COLORS[segment.state] || '#bf6677'}
        ><title>{segment.nodeId}: {STATES.find((entry) => entry.id === segment.state)?.label || segment.state} · minutes {frames[segment.start].minute}–{frames[Math.max(segment.start, segment.end - 1)].minute}</title></rect>)}
        {Array.from({ length: Math.floor((frames.length - 1) / 60) + 1 }, (_, hour) => {
          const frameIndex = Math.min(hour * 60, frames.length - 1);
          const x = LABEL_WIDTH + (frameIndex / Math.max(frames.length - 1, 1)) * plotWidth;
          return <g key={hour}><line className="node-power-hour-line" x1={x} x2={x} y1={TOP - 2} y2={TOP + nodeIds.length * rowHeight - 2} /><text className="node-power-axis-label" x={x} y={chartHeight - 3}>{clockLabel(frames[frameIndex].minute)}</text></g>;
        })}
        <line className="node-power-cursor" x1={LABEL_WIDTH + (minuteIndex / Math.max(frames.length - 1, 1)) * plotWidth} x2={LABEL_WIDTH + (minuteIndex / Math.max(frames.length - 1, 1)) * plotWidth} y1={TOP - 4} y2={TOP + nodeIds.length * rowHeight - 2} />
      </svg>
    </div>}

    {(!compact || compactView === 'nodes') && <>
      <div className="node-workload-legend" aria-label="Executing workload legend">
        <span><b aria-hidden="true">R</b> Real-time</span><span><b aria-hidden="true">F</b> Flexible</span><span><b aria-hidden="true">R+F</b> Mixed</span><span><b aria-hidden="true">—</b> Idle</span>
      </div>
      <div className="node-power-node-grid" aria-label={`Node details at ${clockLabel(frame.minute)}`}>
      {nodeIds.map((nodeId, index) => {
        const state = frame.states[index];
        const label = STATES.find((entry) => entry.id === state)?.label || state || 'Unknown';
        const realtimeUsed = hasWorkloadBreakdown ? Number(frame.realtime_used_gpus[index]) || 0 : null;
        const flexibleUsed = hasWorkloadBreakdown ? Number(frame.flexible_used_gpus[index]) || 0 : null;
        const nodeUsed = Number(frame.used_gpus[index]) || 0;
        const idleActiveGpus = state === 'active' && gpusPerNode > 0 ? Math.max(0, gpusPerNode - nodeUsed) : null;
        const workloadKind = !hasWorkloadBreakdown ? 'Unavailable'
          : realtimeUsed > 0 && flexibleUsed > 0 ? 'Mixed'
            : realtimeUsed > 0 ? 'Real-time' : flexibleUsed > 0 ? 'Flexible' : 'Idle';
        const workMark = workloadKind === 'Mixed' ? 'R+F' : workloadKind === 'Real-time' ? 'R' : workloadKind === 'Flexible' ? 'F' : workloadKind === 'Idle' ? '—' : '?';
        return <article className={`node-power-card state-card-${state}`} key={nodeId}>
          <div className="node-power-card-top"><strong>{nodeId}</strong><span><i className={`node-state-dot state-${state}`} aria-hidden="true" />{label}</span></div>
          <div className={`node-workload-badge workload-${workloadKind.toLowerCase().replace(/[^a-z]+/g, '-')}`} title={hasWorkloadBreakdown ? `Real-time ${number(realtimeUsed, 0)} GPUs; flexible ${number(flexibleUsed, 0)} GPUs` : 'This replay does not include per-type workload allocation'}><b aria-hidden="true">{workMark}</b><span>{workloadKind}</span></div>
          <div className="node-power-card-metrics">
            <span><strong>{number(frame.power_kw[index])}</strong><small>kW IT power</small></span>
            <span><strong>{number(frame.used_gpus[index], 0)}{gpusPerNode ? ` / ${gpusPerNode}` : ''}</strong><small>GPUs in use</small></span>
            {hasWorkloadBreakdown && <span><strong>{number(realtimeUsed, 0)} / {number(flexibleUsed, 0)}</strong><small>real-time / flexible GPUs</small></span>}
            {state === 'active' && idleActiveGpus !== null && <span><strong>{number(idleActiveGpus, 0)}</strong><small>idle active GPUs now</small></span>}
            {state === 'warm' && gpusPerNode > 0 && <span><strong>{number(gpusPerNode, 0)}</strong><small>warm GPUs · ready now</small></span>}
          </div>
        </article>;
      })}
      </div>
    </>}

    <section className="ready-capacity-now" aria-label={`GPU capacity at ${clockLabel(frame.minute)}`}>
      <div className="ready-capacity-card ready-capacity-primary">
        <span>Idle active GPUs now</span>
        <strong>{activeSpare === null ? '—' : number(activeSpare, 1)}</strong>
        <small>Ready immediately; excludes current real-time and flexible work.</small>
      </div>
      <div className="ready-capacity-card">
        <span>Active capacity</span>
        <strong>{activeCapacity === null ? '—' : number(activeCapacity, 0)} GPUs</strong>
        <small>{hasWorkloadBreakdown
          ? `${number(totalRealtimeUsed, 1)} real-time + ${number(totalFlexibleUsed, 1)} flexible in use.`
          : `${number(totalUsed, 1)} GPUs in use.`} Real-time requests dispatch first; flexible work uses remaining active capacity.</small>
      </div>
      <div className="ready-capacity-card">
        <span>Ready now including standby</span>
        <strong>{number(frame.dispatchable_capacity_gpus ?? (activeSpare + warmNodeCount * gpusPerNode), 0)} GPUs</strong>
        <small>Idle active GPUs plus warm-ready GPUs; warm nodes promote with zero modeled minutes.</small>
      </div>
      <div className="ready-capacity-card">
        <span>Warm standby</span>
        <strong>{warmNodeCount} nodes · {gpusPerNode > 0 ? number(warmNodeCount * gpusPerNode, 0) : '—'} GPUs</strong>
        <small>Can be promoted to active immediately; only cold booting has a modeled delay.</small>
      </div>
      <div className="ready-capacity-card">
        <span>Not ready yet</span>
        <strong>{warmingNodeCount} warming · {bootingNodeCount} booting · {offNodeCount} off</strong>
        <small>These nodes do not count as immediate reserve.</small>
      </div>
      {hasRequestTimeline && <div className="ready-capacity-queue" role="status">
        <strong>{waitingNow === 0 ? 'No requests waiting now' : `${waitingNow} request${waitingNow === 1 ? '' : 's'} waiting now`}</strong>
        <span>Observed queue at {clockLabel(frame.minute)}; the forecast gap below is a prediction, not an observed wait.</span>
      </div>}
    </section>

    {!compact && <div className="node-power-time-control">
      <label htmlFor="node-power-minute">Selected minute <strong>{clockLabel(frame.minute)}</strong></label>
      <input id="node-power-minute" type="range" min="0" max={frames.length - 1} step="1" value={minuteIndex} onChange={(event) => selectIndex(Number(event.target.value))} aria-valuetext={`${clockLabel(frame.minute)}, minute ${frame.minute}`} />
      <span>{frames.length} minute frames</span>
    </div>}

    <div className="node-power-summary" aria-live="polite">
      <span><strong>{number(totalUsed, 0)}</strong> GPUs in use{gpusPerNode ? ` / ${nodeIds.length * gpusPerNode} installed` : ''}</span>
      {hasWorkloadBreakdown ? <span><strong>{number(totalRealtimeUsed, 0)}</strong> real-time <small>·</small> <strong>{number(totalFlexibleUsed, 0)}</strong> flexible GPUs</span> : <span>Workload split unavailable in this replay</span>}
      <span><strong>{number(totalPower)} kW</strong> node IT draw</span>
      {Number.isFinite(frame.facility_kw) && <span><strong>{number(frame.facility_kw)} kW</strong> facility draw (includes fixed load and PUE)</span>}
    </div>

    {Number.isFinite(frame.target_warm_nodes) && <section className="warm-reserve-readout" aria-label={`Forecast readiness plan at ${clockLabel(frame.minute)}`}>
      <div className="warm-reserve-readout-heading"><strong>Forecast readiness at {clockLabel(frame.minute)}</strong><span>Forecasted active capacity plus a separate warm-stock target that expands for queued work.</span></div>
      <div className="warm-reserve-readout-metrics">
        <span><strong>{frame.forecast_target_active_nodes}</strong> peak active target in next 40 min</span>
        <span><strong>{frame.forecast_warm_nodes_started}</strong> warm nodes starting activation</span>
        <span><strong>{frame.forecast_cold_nodes_started}</strong> cold nodes starting boot</span>
        <span><strong>{frame.warm_stock_target_nodes}</strong> warm stock target (base {frame.warm_overhead_nodes})</span>
        <span><strong>{frame.target_warm_nodes}</strong> legacy scalar target (diagnostic)</span>
        <span><strong>{frame.warm_reserve_ready_nodes}</strong> warm and ready</span>
        <span><strong>{frame.warm_reserve_pipeline_nodes}</strong> warm or booting toward warm stock (<strong>{frame.warm_reserve_booting_nodes}</strong> booting · <strong>{frame.warm_reserve_warming_nodes}</strong> activating)</span>
        {frame.queued_reserve_demand_nodes > 0 && <span><strong>{frame.queued_reserve_demand_nodes}</strong> node-equivalents of requests still queued</span>}
        <span><strong>{frame.warm_stock_shortfall_nodes}</strong> stock nodes beyond inactive fleet</span>
        <span><strong>{frame.warm_ready_deficit_nodes}</strong> stock nodes not ready yet</span>
        <span><strong>{number(frame.active_spare_gpus, 1)}</strong> idle active GPUs now</span>
        <span><strong>{number(frame.pre_warm_active_shortfall_gpus, 1)}</strong> forecast gap before cold boot capacity is ready</span>
      </div>
      {(frame.warm_stock_shortfall_nodes > 0 || frame.warm_reserve_pipeline_gap_nodes > 0 || frame.readiness_capacity_shortfall_gpus > 0 || frame.forecast_capacity_shortfall_gpus > 0 || frame.warm_stock_shortfall_reason) && <p className="warm-reserve-warning" role="status">
        {frame.warm_stock_shortfall_nodes > 0 && `Desired stock exceeds inactive fleet by ${frame.warm_stock_shortfall_nodes} node(s). `}
        {frame.warm_reserve_pipeline_gap_nodes > 0 && `${frame.warm_reserve_pipeline_gap_nodes} desired stock node(s) have not entered the startup pipeline. `}
        {frame.readiness_capacity_shortfall_gpus > 0 && `Forecast-only readiness gap within startup lead times: ${number(frame.readiness_capacity_shortfall_gpus, 1)} GPUs. This is not an observed request wait. `}
        {frame.forecast_capacity_shortfall_gpus > 0 && `Protected demand exceeds installed fleet by ${number(frame.forecast_capacity_shortfall_gpus, 1)} GPUs. `}
        {frame.warm_stock_shortfall_reason}
      </p>}
      <p className="warm-reserve-readout-note">After dispatch, any real-time requests still queued raise the warm-stock target to cover their total GPU demand, up to the fleet size; when the queue clears, it returns to your configured reserve. OFF nodes take 20 minutes to join warm stock. The planner also promotes ready warm nodes immediately and starts cold boots ahead of forecast demand. The protected demand peak is {number(frame.forecast_window_peak_upper_gpus, 1)} GPUs; margin {number(frame.forecast_margin_gpus, 1)} GPUs ({frame.forecast_margin_source === 'matured_synthetic_window_q95' ? 'replayed synthetic errors' : 'fallback assumption'}). A forecast gap does not say that actual work waited; check the observed queue above. Legacy scalar target {frame.target_warm_nodes} is shown for context only.</p>
    </section>}

  </section>;
}
