import { useEffect, useState } from "react";
import { api, Job, LearningDoc, State, waitForJob } from "../api";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const FIELD: Record<string, string> = {
  title: "Title", short_description: "Short description", collector_description: "Collector description",
  store_tags: "Store tags", search_keywords: "Search keywords",
};

// A bar for a share, with the number written beside it, so the table reads at a glance and without colour.
function Share({ value }: { value: number }) {
  return <span className="share"><span className="share-track" aria-hidden="true"><span style={{ width: pct(value) }} /></span><span className="share-n">{pct(value)}</span></span>;
}

export function Learning({ state, onChange }: { state: State; onChange: () => void }) {
  const [doc, setDoc] = useState<LearningDoc | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const load = () => api.learning().then(setDoc);
  useEffect(() => { load(); }, []);
  if (!doc) return <main className="page"><p className="muted">Loading…</p></main>;

  async function distil() {
    setMsg(null);
    try {
      const { job: id } = await api.distil();
      const j = await waitForJob(id, setJob);
      if (j.error) throw new Error(j.error);
      const r = j.results[0] as { proposed: number } | undefined;
      setMsg(`${r?.proposed ?? 0} new lesson(s) proposed.`);
      await load(); onChange();
    } catch (e) { setMsg(String((e as Error).message)); }
  }
  async function decide(id: string, status: string) {
    try { await api.decide("lesson", id, status, texts[id]); await load(); onChange(); } catch (e) { setMsg(String((e as Error).message)); }
  }
  const proposed = doc.lessons.filter((l) => l.status === "proposed");
  const decided = doc.lessons.filter((l) => l.status !== "proposed");

  return (
    <main className="page narrow">
      <div className="row between">
        <h1>Learning</h1>
        <div className="row">
          {job?.running && <span className="muted">Reading your edits…</span>}
          {msg && <span className="muted small">{msg}</span>}
          <button disabled={!state.key_configured || !doc.changed || !!job?.running} onClick={distil}>Learn from my edits ({doc.changed})</button>
        </div>
      </div>
      <p className="muted">When you approve copy, every change you made is recorded next to what the draft said. Your most telling recent edits go straight into the next drafts as examples. “Learn from my edits” asks Claude for general lessons; you approve each one before it reaches the writer.</p>

      <section className="panel"><h2>How close the drafts are</h2>
        {doc.stats.approvals === 0 ? <p className="muted">Approve a few listings to see this.</p> : (
          <table className="table learn-table"><thead><tr><th>Field</th><th>Kept as drafted</th><th>Words kept (all)</th>
            {doc.stats.approvals > 10 && <th>Words kept (latest 10)</th>}</tr></thead>
            <tbody>{Object.entries(doc.stats.by_field).map(([f, s]) => (
              <tr key={f}><td>{FIELD[f] || f}</td><td><Share value={s.accepted_unchanged} /></td><td><Share value={s.similarity} /></td>
                {doc.stats.approvals > 10 && <td><Share value={s.similarity_latest_10} /></td>}</tr>
            ))}</tbody></table>
        )}
        <p className="muted small">{doc.stats.approvals} approval{doc.stats.approvals === 1 ? "" : "s"} so far.{doc.stats.approvals > 10 ? " If “latest 10” climbs above “all”, the drafts are getting closer to your voice." : " A comparison with the latest 10 appears after more than 10 approvals."}</p>
      </section>

      <section className="panel"><h2>Proposed lessons</h2>
        {proposed.length === 0 && <p className="muted">None waiting.</p>}
        {proposed.map((l) => (
          <article key={l.id} className="example proposed">
            <textarea rows={2} value={texts[l.id] ?? l.text} onChange={(e) => setTexts({ ...texts, [l.id]: e.target.value })} />
            <p className="muted small">From {l.evidence.join(", ")}</p>
            <div className="row"><button onClick={() => decide(l.id, "approved")}>Approve</button>
              <button className="secondary" onClick={() => decide(l.id, "rejected")}>Reject</button></div>
          </article>
        ))}
      </section>
      {decided.length > 0 && (
        <section className="panel"><h2>Decided lessons</h2>
          <ul>{decided.map((l) => <li key={l.id}><span className={`badge ${l.status === "approved" ? "ok" : "bad"}`}>{l.status}</span> {l.text}
            {l.status === "approved" && <button className="link" onClick={() => decide(l.id, "rejected")}>Retire</button>}</li>)}</ul>
        </section>
      )}
      {doc.repeated_removals.length > 0 && (
        <section className="panel"><h2>Words you keep removing</h2>
          <ul>{doc.repeated_removals.slice(0, 15).map((r) => <li key={r.phrase}><strong>{r.phrase}</strong> <span className="muted small">in {r.items.length} listings</span></li>)}</ul>
          <p className="muted small">Add any of these to Phrases to watch on the {state.site_kind === "product" ? "Brand" : "Artist context"} page.</p>
        </section>
      )}
      <section className="panel"><h2>Recent edits</h2>
        {doc.edits.filter((e) => e.changed).length === 0 && <p className="muted">No edits recorded yet.</p>}
        {doc.edits.filter((e) => e.changed).slice(0, 25).map((e) => (
          <article key={e.id} className="edit">
            <p className="muted small"><a href={`#/listings/${e.item}`} title={e.id}>{state.items.find((i) => i.id === e.item)?.title || e.item}</a> · {FIELD[e.field] || e.field} · {e.event} · {pct(e.diff.similarity)} kept</p>
            <p className="was">{e.proposed}</p><p className="now">{e.final}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
