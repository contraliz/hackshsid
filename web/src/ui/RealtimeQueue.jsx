import { useEffect, useMemo, useState } from 'react';
import { formatNumber } from './Controls.jsx';

const SAMPLE_REQUESTS = [
  { id: 'std-long', name: 'Standard batch A', tier: 'standard', arrival_minute: 0, gpu_count: 50, duration_minutes: 20 },
  { id: 'std-small', name: 'Standard serving B', tier: 'standard', arrival_minute: 0, gpu_count: 20, duration_minutes: 8 },
  { id: 'pro-arrives', name: 'Pro inference A', tier: 'pro', arrival_minute: 1, gpu_count: 20, duration_minutes: 6 },
  { id: 'std-later', name: 'Standard batch C', tier: 'standard', arrival_minute: 5, gpu_count: 25, duration_minutes: 5 },
];

function minuteLabel(value) {
  if (value === null || value === undefined) return '—';
  const hour = Math.floor(value / 60);
  const minute = value % 60;
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function stateAt(request, snapshot, result) {
  if (request.status === 'rejected') return 'rejected';
  if (!snapshot) return 'not run';
  if (snapshot.completed.includes(request.id)) return 'completed';
  if (snapshot.running.some((item) => item.request_id === request.id)) return 'running';
  if (snapshot.waiting_order.includes(request.id)) return 'waiting';
  if (request.arrival_minute > snapshot.minute) return 'upcoming';
  const arrived = snapshot.events.some((event) => event.type === 'arrived' && event.request_id === request.id);
  return arrived ? 'started' : (result?.timeline?.length ? 'completed' : 'not run');
}

export function RealtimeQueue({ controls, scheduleResult }) {
  const [requests, setRequests] = useState(SAMPLE_REQUESTS);
  const [hour, setHour] = useState(12);
  const [draftTier, setDraftTier] = useState('pro');
  const [draftGpus, setDraftGpus] = useState('24');
  const [draftDuration, setDraftDuration] = useState('8');
  const [draftArrival, setDraftArrival] = useState('0');
  const [result, setResult] = useState(null);
  const [position, setPosition] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setResult(null);
    setPosition(0);
  }, [controls.scenario, controls.gpu_count]);

  const snapshot = result?.timeline?.[position] ?? null;
  const matchingCapacity = scheduleResult?.case?.scenario === controls.scenario
    && Number(scheduleResult?.case?.gpu_count) === Number(controls.gpu_count)
    ? scheduleResult.case.realtime_gpus
    : result?.realtime_gpus_by_hour;
  const currentUsed = useMemo(
    () => snapshot?.running.reduce((total, item) => total + item.gpu_count, 0) ?? 0,
    [snapshot],
  );

  function editRequest(id, key, value) {
    setRequests((current) => current.map((item) => item.id === id ? { ...item, [key]: value } : item));
    setResult(null);
    setPosition(0);
  }

  function addRequest() {
    const next = requests.length + 1;
    setRequests((current) => [...current, {
      id: `custom-${next}-${Date.now().toString(36)}`,
      name: `${draftTier === 'pro' ? 'Pro' : 'Standard'} request ${next}`,
      tier: draftTier,
      arrival_minute: Number(draftArrival),
      gpu_count: Number(draftGpus),
      duration_minutes: Number(draftDuration),
    }]);
    setResult(null);
    setError('');
  }

  function resetSample() {
    setRequests(SAMPLE_REQUESTS);
    setHour(12);
    setResult(null);
    setPosition(0);
    setError('');
  }

  async function runSimulation() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/realtime-queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requests,
          scenario: controls.scenario,
          gpu_count: Number(controls.gpu_count),
          hour: Number(hour),
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
      setResult(body);
      setPosition(0);
    } catch (requestError) {
      setResult(null);
      setError(requestError.message || 'The priority queue could not complete this simulation.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="queue-section" aria-labelledby="queue-title">
      <div className="section-title-row">
        <div>
          <h2 id="queue-title">Real-time request priority queue</h2>
          <p className="section-unit">Replay subscriber requests against one hour’s reserved real-time GPU capacity</p>
        </div>
        {result && <span className="capacity-badge">{result.capacity_gpus} reserved GPUs</span>}
      </div>

      <p className="queue-disclosure">
        Pro requests take the next available fitting slot ahead of queued Standard requests. Running requests are never interrupted. Tier is simulated subscriber metadata; this prototype has no accounts, billing, or live inference.
      </p>

      <div className="queue-capacity-row">
        <label htmlFor="queue-hour">Use reservation from hour</label>
        <select id="queue-hour" value={hour} onChange={(event) => { setHour(Number(event.target.value)); setResult(null); }}>
          {Array.from({ length: 24 }, (_, index) => <option key={index} value={index}>{String(index).padStart(2, '0')}:00 · {matchingCapacity?.[index] ?? '—'} reserved GPUs</option>)}
        </select>
        <span>Scenario capacity changes with the main schedule settings.</span>
      </div>

      <div className="queue-table-wrap">
        <table className="queue-table">
        <thead><tr><th>Request</th><th>Subscriber tier</th><th>Arrival · min</th><th>GPUs</th><th>Duration · min</th><th>Actions</th></tr></thead>
          <tbody>
            {requests.map((request) => (
              <tr key={request.id}>
                <th scope="row">{request.name}</th>
                <td>
                  <select aria-label={`${request.name} subscriber tier`} value={request.tier} onChange={(event) => editRequest(request.id, 'tier', event.target.value)}>
                    <option value="pro">Pro</option><option value="standard">Standard</option>
                  </select>
                </td>
                <td><input aria-label={`${request.name} arrival minute`} type="number" min="0" max="119" step="1" value={request.arrival_minute} onChange={(event) => editRequest(request.id, 'arrival_minute', event.target.value)} /></td>
                <td><input aria-label={`${request.name} GPU demand`} type="number" min="1" max="512" step="1" value={request.gpu_count} onChange={(event) => editRequest(request.id, 'gpu_count', event.target.value)} /></td>
                <td><input aria-label={`${request.name} duration`} type="number" min="1" max="120" step="1" value={request.duration_minutes} onChange={(event) => editRequest(request.id, 'duration_minutes', event.target.value)} /></td>
                <td><button type="button" className="queue-remove" aria-label={`Remove ${request.name}`} onClick={() => { setRequests((current) => current.filter((item) => item.id !== request.id)); setResult(null); }}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="queue-editor-row" aria-label="Add a synthetic request">
        <label>New request tier<select value={draftTier} onChange={(event) => setDraftTier(event.target.value)}><option value="pro">Pro</option><option value="standard">Standard</option></select></label>
        <label>Arrival minute<input type="number" min="0" max="119" step="1" value={draftArrival} onChange={(event) => setDraftArrival(event.target.value)} /></label>
        <label>GPUs<input type="number" min="1" max="512" step="1" value={draftGpus} onChange={(event) => setDraftGpus(event.target.value)} /></label>
        <label>Duration<input type="number" min="1" max="120" step="1" value={draftDuration} onChange={(event) => setDraftDuration(event.target.value)} /></label>
        <button type="button" className="quiet-button" disabled={requests.length >= 32} onClick={addRequest}>Add request</button>
        <button type="button" className="quiet-button" onClick={resetSample}>Reset sample</button>
      </div>

      <div className="queue-actions">
        <button type="button" className="run-button queue-run" onClick={runSimulation} disabled={busy}>
          {busy ? 'Simulating…' : 'Run queue simulation'}
        </button>
        {result && (
          <div className="replay-controls" aria-label="Queue replay controls">
            <button type="button" className="quiet-button" onClick={() => setPosition(0)}>Replay</button>
            <button type="button" className="quiet-button" disabled={position >= result.timeline.length - 1} onClick={() => setPosition((current) => Math.min(result.timeline.length - 1, current + 1))}>Step next</button>
            <label htmlFor="queue-timeline">Event {result.timeline.length ? position + 1 : 0} / {result.timeline.length}</label>
            <input id="queue-timeline" type="range" min="0" max={Math.max(0, result.timeline.length - 1)} value={position} onChange={(event) => setPosition(Number(event.target.value))} disabled={!result.timeline.length} />
          </div>
        )}
      </div>

      {error && <p className="queue-error" role="alert">{error}</p>}
      {result && (
        <div className="queue-simulation" aria-live="polite">
          <div className="queue-state-heading">
            <strong>{snapshot ? `At ${minuteLabel(snapshot.minute)}` : 'No arrivals in this simulation'}</strong>
            <span>{formatNumber(currentUsed)} / {result.capacity_gpus} reserved GPUs running</span>
          </div>
          {snapshot && <p className="queue-event-line">{snapshot.events.length ? snapshot.events.map((event) => `${event.name}: ${event.type}`).join(' · ') : 'No new arrivals or completions at this point.'}</p>}
          <div className="queue-state-grid">
            {requests.map((request) => {
              const status = stateAt(result.requests.find((item) => item.id === request.id), snapshot, result);
              const waitingPosition = snapshot?.waiting_order.indexOf(request.id) ?? -1;
              const record = result.requests.find((item) => item.id === request.id);
              const timing = status === 'running' ? `finishes ${minuteLabel(record.ends_at_minute)}`
                : status === 'completed' ? `finished ${minuteLabel(record.completed_at_minute)}`
                  : status === 'waiting' ? `queue position ${waitingPosition + 1}`
                    : status === 'rejected' ? record.reason : status === 'upcoming' ? `arrives ${minuteLabel(request.arrival_minute)}` : '';
              return (
                <article className={`queue-request-card is-${status.replaceAll(' ', '-')}`} key={request.id}>
                  <div><strong>{request.name}</strong><span className={`tier-pill tier-${request.tier}`}>{request.tier}</span></div>
                  <span className="queue-request-status">{status}</span>
                  <small>{timing || `${request.gpu_count} GPUs · ${request.duration_minutes} min`}</small>
                </article>
              );
            })}
          </div>
          <p className="queue-policy-note">Backfill rule: if no queued Pro request fits the free GPUs, the next fitting Standard request may start. Arrival order is preserved among eligible requests within each tier.</p>
        </div>
      )}
    </section>
  );
}
