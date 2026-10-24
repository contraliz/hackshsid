import './LiveTrafficView.css';
import { formatNumber } from './Controls.jsx';

const MAX_CARDS = 8;
const MAX_EVENTS = 10;

function clockLabel(minute) {
  const safeMinute = Math.max(0, Number(minute) || 0);
  return `${String(Math.floor(safeMinute / 60)).padStart(2, '0')}:${String(safeMinute % 60).padStart(2, '0')}`;
}

function stateAt(request, minute) {
  if (request.rejected_at_minute != null && request.rejected_at_minute <= minute) return 'rejected';
  if (request.completed_at_minute != null && request.completed_at_minute <= minute) return 'completed';
  if (request.started_at_minute != null && request.started_at_minute <= minute) return 'running';
  return 'waiting';
}

function buildCostPath(frames, minute) {
  const visible = frames.slice(0, minute + 1);
  if (!visible.length) return { points: '', maxCost: 1, current: 0 };
  const current = Number(visible.at(-1)?.cumulative_cost_cny) || 0;
  const maxCost = Math.max(1, ...visible.map((frame) => Number(frame.cumulative_cost_cny) || 0));
  const sampleCount = 60;
  const samples = visible.length <= sampleCount
    ? visible
    : Array.from({ length: sampleCount }, (_, index) => visible[Math.round(index * (visible.length - 1) / (sampleCount - 1))]);
  const points = samples.map((frame, index) => {
    const x = samples.length === 1 ? 0 : (index / (samples.length - 1)) * 100;
    const y = 38 - ((Number(frame.cumulative_cost_cny) || 0) / maxCost) * 32;
    return `${x},${y}`;
  }).join(' ');
  return { points, maxCost, current };
}

function RequestCard({ request, status }) {
  return (
    <li className={`live-request-card is-${status}`}>
      <div className="live-request-heading">
        <strong>{request.id}</strong>
        <span className={`tier-pill ${request.tier === 'pro' ? 'tier-pro' : 'tier-standard'}`}>{request.tier || 'standard'}</span>
      </div>
      <p>{request.gpus} GPUs · {request.duration_minutes} min</p>
      <small>{status === 'running' ? `Started ${clockLabel(request.started_at_minute)}` : `Arrived ${clockLabel(request.arrival_minute)}`}</small>
    </li>
  );
}

export function LiveTrafficView({ replay, minute, compact = false }) {
  const frames = Array.isArray(replay?.frames) ? replay.frames : [];
  const requests = Array.isArray(replay?.requests) ? replay.requests : [];
  const currentMinute = Math.min(Math.max(0, Number(minute) || 0), Math.max(0, frames.length - 1));
  const frame = frames[currentMinute] || {};
  const arrived = requests.filter((request) => Number(request.arrival_minute) <= currentMinute);
  const waiting = arrived.filter((request) => stateAt(request, currentMinute) === 'waiting')
    .sort((a, b) => a.arrival_minute - b.arrival_minute || String(a.id).localeCompare(String(b.id)));
  const running = arrived.filter((request) => stateAt(request, currentMinute) === 'running');
  const completed = arrived.filter((request) => stateAt(request, currentMinute) === 'completed');
  const rejected = arrived.filter((request) => stateAt(request, currentMinute) === 'rejected');
  const cost = buildCostPath(frames, currentMinute);

  const events = [];
  for (const request of requests) {
    const milestones = [
      ['arrival_minute', 'arrived'],
      ['started_at_minute', 'started'],
      ['completed_at_minute', 'completed'],
      ['rejected_at_minute', 'rejected'],
    ];
    for (const [field, verb] of milestones) {
      const at = request[field];
      if (at != null && Number(at) <= currentMinute) events.push({ request, at: Number(at), verb });
    }
  }
  events.sort((a, b) => b.at - a.at || String(a.request.id).localeCompare(String(b.request.id)));

  if (!frames.length) {
    return <section className={`live-traffic${compact ? ' is-compact' : ''}`} aria-labelledby="live-traffic-title"><h3 id="live-traffic-title">Live request replay</h3><p className="live-empty">Run a simulation to show incoming requests, the waiting queue, running requests, and cumulative electricity cost.</p></section>;
  }

  return (
    <section className={`live-traffic${compact ? ' is-compact' : ''}`} aria-labelledby="live-traffic-title">
      <div className="live-traffic-title-row">
        <div>
          <h3 id="live-traffic-title">Live request replay</h3>
          <p className="live-traffic-note">Deterministic synthetic traffic · simulation time {clockLabel(currentMinute)} · no live hardware or customer traffic</p>
        </div>
        <span className="live-time-badge">Day {clockLabel(currentMinute)}</span>
      </div>

      <div className="live-metric-grid" aria-label="Current replay metrics">
        <div className="live-metric live-cost"><span>Cumulative grid cost</span><strong>¥{formatNumber(frame.cumulative_cost_cny, 2)}</strong><small>Illustrative tariff, through {clockLabel(currentMinute)}</small></div>
        <div className="live-metric"><span>Grid electricity used</span><strong>{formatNumber(frame.cumulative_grid_kwh, 1)} kWh</strong><small>Renewable supplied {formatNumber(frame.renewable_used_kwh, 1)} kWh</small></div>
        <div className="live-metric"><span>Current facility power</span><strong>{formatNumber(frame.facility_kw, 1)} kW</strong><small>{formatNumber(frame.grid_kwh, 2)} grid kWh this interval</small></div>
        <div className="live-metric"><span>Request states</span><strong>{waiting.length} waiting · {running.length} running</strong><small>{completed.length} completed · {rejected.length} rejected by now</small></div>
      </div>

      <div className="live-detail-grid">
        <div className="live-panel live-cost-panel">
          <div className="live-panel-heading"><h4>Accumulated electricity cost</h4><span>¥ CNY</span></div>
          <svg className="live-cost-chart" viewBox="0 0 100 44" role="img" aria-label={`Cumulative grid cost through ${clockLabel(currentMinute)}: ${formatNumber(cost.current, 2)} Chinese yuan`}>
            <line x1="0" y1="38" x2="100" y2="38" />
            <polyline points={cost.points} />
          </svg>
          <div className="live-chart-axis"><span>00:00</span><span>{clockLabel(currentMinute)}</span><strong>¥{formatNumber(cost.current, 2)}</strong></div>
          <p className="live-chart-footnote">Cost is cumulative only up to the selected minute; values are illustrative.</p>
        </div>

        <div className="live-panel">
          <div className="live-panel-heading"><h4>Incoming request feed</h4><span>{events.length} events so far</span></div>
          {events.length ? <ol className="live-event-feed">{events.slice(0, MAX_EVENTS).map(({ request, at, verb }, index) => (
            <li key={`${request.id}-${verb}-${at}-${index}`}>
              <time>{clockLabel(at)}</time><span className={`live-event-mark is-${verb}`} aria-hidden="true" />
              <p><strong>{request.id}</strong> {verb}<span> · {request.tier || 'standard'} · {request.gpus} GPUs</span></p>
            </li>
          ))}</ol> : <p className="live-empty">No request arrivals yet at this time.</p>}
          {events.length > MAX_EVENTS && <p className="live-list-more">Showing latest {MAX_EVENTS} of {events.length} events.</p>}
        </div>
      </div>

      <div className="live-detail-grid live-request-lists">
        <div className="live-panel">
          <div className="live-panel-heading"><h4>Waiting queue</h4><span>{waiting.length} total · arrival order</span></div>
          {waiting.length ? <ul className="live-request-list">{waiting.slice(0, compact ? 4 : MAX_CARDS).map((request) => <RequestCard key={request.id} request={request} status="waiting" />)}</ul> : <p className="live-empty">The queue is empty at this minute.</p>}
          {waiting.length > (compact ? 4 : MAX_CARDS) && <p className="live-list-more">Showing {compact ? 4 : MAX_CARDS} of {waiting.length} waiting requests.</p>}
        </div>
        <div className="live-panel">
          <div className="live-panel-heading"><h4>Running requests</h4><span>{running.length} total</span></div>
          {running.length ? <ul className="live-request-list">{running.slice(0, compact ? 4 : MAX_CARDS).map((request) => <RequestCard key={request.id} request={request} status="running" />)}</ul> : <p className="live-empty">No requests are running at this minute.</p>}
          {running.length > (compact ? 4 : MAX_CARDS) && <p className="live-list-more">Showing {compact ? 4 : MAX_CARDS} of {running.length} running requests.</p>}
        </div>
      </div>
    </section>
  );
}
