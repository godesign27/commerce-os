import { useCallback, useEffect, useState } from "react";
import { api, PublishQueue, QueueRow } from "../api";
import { ago } from "./Photos";
import { StatusBadge } from "../components/Status";

// Everything approved for the store, in one place to send it (B-071). Publishing here only asks: the worker runs its
// final check and writes. Each request names the version shown here, so a listing changed since this page loaded is
// refused rather than published unseen.
function price(r: QueueRow) {
  if (!r.price) return null;
  return (r.price.amount_minor / 100).toLocaleString("en-US", { style: "currency", currency: r.price.currency });
}

function Row({ r, children, lead }: { r: QueueRow; children?: React.ReactNode; lead?: React.ReactNode }) {
  const facts = [r.sold_as, price(r), r.size].filter(Boolean).join(" · ");
  return (
    <li className="pq-row">
      {lead || <span className="pq-lead" />}
      {r.image ? <img src={`/${r.image}`} alt="" loading="lazy" /> : <div className="pq-noimage" />}
      <div className="pq-body">
        <a className="pq-title" href={`#/listings/${r.id}`}><strong>{r.title || r.source}</strong></a>
        {facts && <span className="muted small">{facts}</span>}
        {children}
      </div>
    </li>
  );
}

function plural(n: number) { return `${n} listing${n === 1 ? "" : "s"}`; }

export function Publish({ onChange }: { onChange: () => void }) {
  const [q, setQ] = useState<PublishQueue | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  const [said, setSaid] = useState<Record<string, string>>({});
  const load = useCallback(() => api.publishQueue().then(setQ).catch((e) => setError(String(e.message))), []);
  useEffect(() => { load(); }, [load]);
  const active = !!q?.available && (q.working.length > 0 || q.problems.some((r) => r.checking));
  useEffect(() => {
    if (!active) { onChange(); return; }
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
  }, [active, load, onChange]);

  async function send(rows: QueueRow[]) {
    setBusy(true); setError(null);
    try {
      const res = await api.publishMany(rows.map((r) => ({ id: r.id, change_set_hash: r.change_set_hash! })));
      setQ(res.queue);
      setChosen(new Set());
      setRefused(Object.fromEntries(res.results.filter((x) => !x.ok).map((x) => [x.id, x.error || "Refused."])));
      onChange();
    } catch (e) { setError(String((e as Error).message)); await load(); }
    setBusy(false);
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); await load(); onChange(); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }

  if (!q) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  if (!q.available) return <main className="page"><h1>Publish</h1><p className="muted">{q.reason} <a href="#/start">Getting started →</a></p></main>;

  const target = q.target.toLowerCase();
  // Every listing can be ticked. Only a ready one can go: a ticked one that isn't ready says why when you press
  // Publish, and it's never sent, because the server has no approved version to send.
  const tickable = [...q.ready, ...q.waiting];
  const selected = q.ready.filter((r) => chosen.has(r.id));
  const notReady = q.waiting.filter((r) => chosen.has(r.id));
  const ticked = selected.length + notReady.length;
  const allChosen = tickable.length > 0 && ticked === tickable.length;
  const press = () => {
    setSaid(Object.fromEntries(notReady.map((r) => [r.id, `Not published: ${(r.status.detail || r.status.label).toLowerCase()}.`])));
    if (selected.length) send(selected);
  };
  const off = q.kill_switch.on;
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChosen(next);
    setSaid({});
  };

  return (
    <main className="page">
      <div className="row between page-head">
        <h1>Publish</h1>
        <div className="row">
          {!q.kill_switch.forced && (
            <button className="link" disabled={busy} onClick={() => act(() => api.killSwitch(!off))}>
              {off ? "Switch writing back on" : "Stop all writing"}</button>)}
          <button disabled={busy || off || !ticked} onClick={press}>
            {busy ? "Publishing…" : selected.length ? `Publish ${selected.length}` : "Publish"}</button>
        </div>
      </div>
      {q.live
        ? <p className="pq-target small"><strong>Publishing to: {q.target}.</strong> Each listing goes into {q.display_name} as a Draft.
            Shoppers can't see it until you set it to Active in the store's admin.</p>
        : <p className="pq-target small"><strong>Publishing to: {q.target}.</strong> Each listing goes in as a hidden draft on
            this computer. {q.display_name} itself isn't changed, so nothing appears on your site.</p>}
      {off && <p className="banner small">Writing is switched off{q.kill_switch.forced ? ` by ${q.kill_switch.by}` : ""}, so nothing can be published.</p>}
      {!q.worker.running && <p className="small warn-text">The publishing worker isn't running, so anything you publish will wait. Start Commerce OS with ./start.sh.</p>}
      {q.worker.running && !q.worker.ok && q.worker.reason && <p className="small warn-text">{q.worker.reason}</p>}
      {error && <p className="error">{error}</p>}

      <label className="pq-all small">
        <input type="checkbox" checked={allChosen} disabled={!tickable.length}
          ref={(el) => { if (el) el.indeterminate = ticked > 0 && !allChosen; }}
          onChange={() => { setChosen(allChosen ? new Set() : new Set(tickable.map((r) => r.id))); setSaid({}); }} />
        Select all
      </label>
      {notReady.length > 0 && <span className="small muted"> {notReady.length} ticked {notReady.length === 1 ? "isn't" : "aren't"} ready yet, so {notReady.length === 1 ? "it" : "they"} won't be published.</span>}

      {q.problems.length > 0 && (
        <section className="pq-section" aria-labelledby="pq-problems">
          <h2 id="pq-problems">Needs a look <span className="pill">{q.problems.length}</span></h2>
          <ul className="pq-list">
            {q.problems.map((r) => (
              <Row key={r.id} r={r}>
                {r.state === "FAILED" ? (
                  <div className="small"><p className="error">{r.update ? "Not updated. Nothing in the store changed." : "Not published. Nothing went into the store."}</p>
                    <ul>{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
                    <button className="secondary" disabled={busy || off} onClick={() => send([r])}>{r.update ? "Send the update again" : "Publish again"}</button></div>
                ) : (
                  <div className="small warn-text">
                    {r.finding === "mismatch"
                      ? <p>The store has this product, but it doesn't match what you approved ({r.fields.join(", ")}). Nothing will overwrite it: this needs your decision.</p>
                      : <p>The result wasn't seen, so it may or may not have gone in. Publishing again could add it twice, so check the store first.</p>}
                    <button className="secondary" disabled={busy || r.checking} onClick={() => act(() => api.publishRecheck(r.id))}>{r.checking ? "Checking…" : "Check again"}</button>
                  </div>)}
                {refused[r.id] && <span className="small error">{refused[r.id]}</span>}
              </Row>))}
          </ul>
        </section>)}

      <section className="pq-section" aria-labelledby="pq-ready">
        <h2 id="pq-ready">Ready to publish <span className="muted">{q.ready.length}</span></h2>
        {q.ready.length > 0 ? (
          <ul className="pq-list">
            {q.ready.map((r) => (
              <Row key={r.id} r={r} lead={
                <input type="checkbox" checked={chosen.has(r.id)} aria-label={`Select ${r.title || r.source}`} onChange={() => toggle(r.id)} />}>
                <span className="muted small">{r.update ? <><span className="badge">Update</span> to the product already in the store, approved {ago(r.approved_at)}</> : <>Approved {ago(r.approved_at)}</>}</span>
                {refused[r.id] && <span className="small error">{refused[r.id]}</span>}
              </Row>))}
          </ul>
        ) : (
          <p className="muted">Nothing yet. A listing appears here once you approve it for the store.{q.waiting.length > 0 && <> {plural(q.waiting.length)} below {q.waiting.length === 1 ? "needs" : "need"} something from you first.</>}</p>
        )}
      </section>

      {q.working.length > 0 && (
        <section className="pq-section" aria-labelledby="pq-working" role="status">
          <h2 id="pq-working">Publishing <span className="muted">{q.working.length}</span></h2>
          <ul className="pq-list">
            {q.working.map((r) => <Row key={r.id} r={r}><span className="small">{r.state === "QUEUED" ? "Waiting for the worker's final check." : "Publishing…"}</span></Row>)}
          </ul>
        </section>)}

      {q.waiting.length > 0 && (
        <section className="pq-section" aria-labelledby="pq-waiting">
          <h2 id="pq-waiting">Not ready yet <span className="muted">{q.waiting.length}</span></h2>
          <ul className="pq-list">
            {q.waiting.map((r) => (
              <Row key={r.id} r={r} lead={<input type="checkbox" checked={chosen.has(r.id)} aria-label={`Select ${r.title || r.source}`} onChange={() => toggle(r.id)} />}>
                <span className="card-status"><StatusBadge status={r.status} />{r.status.detail && <span className="small">{r.status.detail}</span>}</span>
                <ul className="small pq-next">{r.next.map((x) => <li key={x}>{x}</li>)}</ul>
                {said[r.id] && <span className="small error" role="status">{said[r.id]}</span>}
                <a className="small" href={`#/listings/${r.id}`}>Open the listing →</a>
              </Row>))}
          </ul>
        </section>)}
      {q.not_drafted > 0 && <p className="muted small">{plural(q.not_drafted)} not drafted yet. <a href="#/listings">Go to Listings →</a></p>}

      {q.changed.length > 0 && (
        <section className="pq-section" aria-labelledby="pq-changed">
          <h2 id="pq-changed">Changed since published <span className="muted">{q.changed.length}</span></h2>
          <p className="muted small">These are already in the store, and you've changed them here since. Open one to see what an update
            would change, then approve the update. Anything edited in the store's admin is kept.</p>
          <ul className="pq-list">
            {q.changed.map((r) => (
              <Row key={r.id} r={r}>
                <ul className="small pq-next">{r.next.map((x) => <li key={x}>{x}</li>)}</ul>
                <a className="small" href={`#/listings/${r.id}`}>Review the update →</a>
              </Row>))}
          </ul>
        </section>)}

      {q.published.length > 0 && (
        <section className="pq-section" aria-labelledby="pq-published">
          <h2 id="pq-published">Published to the {target} <span className="muted">{q.published.length}</span></h2>
          <ul className="pq-list">
            {q.published.map((r) => (
              <Row key={r.id} r={r}><span className="muted small"><span className="badge ok">✓ Confirmed</span> {q.live ? "Draft in the store's admin" : "Hidden draft"}, {ago(r.published_at)}. Product {r.product_id}</span></Row>))}
          </ul>
        </section>)}
    </main>
  );
}
