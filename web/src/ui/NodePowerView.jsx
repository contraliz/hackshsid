import { useMemo, useState } from 'react';
import './NodePowerView.css';

const STATES = [
  { id: 'active', label: 'Active', color: '#1677f2' },
  { id: 'warm', label: 'Warm standby', color: '#45a87a' },
  { id: 'warming', label: 'Warming', color: '#e0a12e' },
  { id: 'booting', label: 'Booting', color: '#b184d3' },
  { id: 'off', label: 'Powered off', color: '#d8dee8' },
];
const STATE_COLORS = Object.fromEntries(STATES.map(({ id, color }) => [id, color]));
const CHART_WIDTH = 1200;
const LABEL_WIDTH = 116;
const ROW_HEIGHT = 14;
const TOP = 8;

function clockLabel(minute) {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
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
  const rowHeight = compact ? 10 : ROW_HEIGHT;
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

  return <section className={`node-power-view${compact ? ' is-compact' : ''}`} aria-labelledby="node-power-title">
    <div className="node-power-heading">
      <div><h3 id="node-power-title">Node power states</h3><p>{compact ? `All ${nodeIds.length} nodes · click the timeline to inspect any minute.` : 'Observed node states across the simulation; select a minute to inspect power and GPU occupancy.'}</p></div>
      <div className="node-power-total" aria-live="polite"><span>Node IT draw</span><strong>{number(totalPower)} kW</strong></div>
    </div>

    {compact && <div className="node-power-view-tabs" role="group" aria-label="Node information view">
      <button type="button" aria-pressed={compactView === 'timeline'} className={compactView === 'timeline' ? 'is-selected' : ''} onClick={() => setCompactView('timeline')}>State timeline</button>
      <button type="button" aria-pressed={compactView === 'nodes'} className={compactView === 'nodes' ? 'is-selected' : ''} onClick={() => setCompactView('nodes')}>Node details</button>
    </div>}

    {(!compact || compactView === 'timeline') && <div className="node-power-legend" aria-label="Node state legend">
      {STATES.map((state) => <span key={state.id}><i className={`node-state-dot state-${state.id}`} aria-hidden="true" />{state.label}</span>)}
    </div>}

    {(!compact || compactView === 'timeline') && <div className="node-power-chart-wrap">
      <svg className="node-power-chart" viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`} role="img" aria-labelledby="node-power-chart-title node-power-chart-description" onClick={selectChartPosition}>
        <title id="node-power-chart-title">Power state history for {nodeIds.length} nodes over {frames.length} minutes</title>
        <desc id="node-power-chart-description">Each row represents one node. Blue is active, green is warm standby, amber is warming, purple is booting, and gray is powered off. Use the minute slider below to select a time.</desc>
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

    {!compact && <div className="node-power-time-control">
      <label htmlFor="node-power-minute">Selected minute <strong>{clockLabel(frame.minute)}</strong></label>
      <input id="node-power-minute" type="range" min="0" max={frames.length - 1} step="1" value={minuteIndex} onChange={(event) => selectIndex(Number(event.target.value))} aria-valuetext={`${clockLabel(frame.minute)}, minute ${frame.minute}`} />
      <span>{frames.length} minute frames</span>
    </div>}

    <div className="node-power-summary" aria-live="polite">
      <span><strong>{number(totalUsed, 0)}</strong> GPUs in use{gpusPerNode ? ` / ${nodeIds.length * gpusPerNode} installed` : ''}</span>
      <span><strong>{number(totalPower)} kW</strong> node IT draw</span>
      {Number.isFinite(frame.facility_kw) && <span><strong>{number(frame.facility_kw)} kW</strong> facility draw (includes fixed load and PUE)</span>}
    </div>

    {(!compact || compactView === 'nodes') && <div className="node-power-node-grid" aria-label={`Node details at ${clockLabel(frame.minute)}`}>
      {nodeIds.map((nodeId, index) => {
        const state = frame.states[index];
        const label = STATES.find((entry) => entry.id === state)?.label || state || 'Unknown';
        return <article className={`node-power-card state-card-${state}`} key={nodeId}>
          <div className="node-power-card-top"><strong>{nodeId}</strong><span><i className={`node-state-dot state-${state}`} aria-hidden="true" />{label}</span></div>
          <div className="node-power-card-metrics">
            <span><strong>{number(frame.power_kw[index])}</strong><small>kW IT power</small></span>
            <span><strong>{number(frame.used_gpus[index], 0)}{gpusPerNode ? ` / ${gpusPerNode}` : ''}</strong><small>GPUs in use</small></span>
          </div>
        </article>;
      })}
    </div>}
  </section>;
}
