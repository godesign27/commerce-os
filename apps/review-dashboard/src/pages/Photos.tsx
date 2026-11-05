import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Job, Photo, PhotosDoc, StatusId, waitForJob } from "../api";
import { StatusBadge } from "../components/Status";

// Every photo in the pipeline, where it is now and when each step happened (B-062).
type Filter = "all" | StatusId;
type Order = "recent" | "name";

export function ago(at: string | null, now = Date.now()): string {
  if (!at) return "time not recorded";
  const s = Math.max(0, (now - Date.parse(at)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  if (d < 30) return d === 1 ? "yesterday" : `${d} days ago`;
  return new Date(at).toLocaleDateString();
}

export function Photos({ onChange }: { onChange: () => void }) {
  const [doc, setDoc] = useState<PhotosDoc | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [order, setOrder] = useState<Order>("recent");
  const [busy, setBusy] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.photos().then(setDoc).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: doc?.photos.length || 0 };
    for (const p of doc?.photos || []) if (p.status) c[p.status.id] = (c[p.status.id] || 0) + 1;
    return c;
  }, [doc]);
  const shown = useMemo(() => {
    const rows = (doc?.photos || []).filter((p) => filter === "all" || p.status?.id === filter);
    return [...rows].sort((a, b) => order === "name" ? a.source.localeCompare(b.source)
      : (b.updated_at || "").localeCompare(a.updated_at || ""));
  }, [doc, filter, order]);

  async function decide(p: Photo, body: Parameters<typeof api.decidePhoto>[1]) {
    setBusy(p.id); setError(null);
    try {
      const row = await api.decidePhoto(p.id, body);
      setDoc((d) => d && { ...d, photos: d.photos.map((x) => x.id === row.id ? row : x),
        pending: d.photos.filter((x) => (x.id === row.id ? row : x).stage === "not-applied").length });
      onChange();
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(null);
  }

  async function apply() {
    setError(null);
    try {
      const { job: id } = await api.applyPhotos();
      const j = await waitForJob(id, setJob);
      if (j.error) setError(j.error);
      await load(); onChange();
    } catch (e) { setError(String((e as Error).message)); }
  }

  async function lookForPhotos() {
    setError(null);
    try {
      const { job: id } = await api.scanInbox();
      const j = await waitForJob(id, setJob);
      if (j.error) setError(j.error);
      await load(); onChange();
    } catch (e) { setError(String((e as Error).message)); }
  }

  if (!doc) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  return (
    <main className="page">
      <div className="row between page-head">
        <h1>Photos</h1>
        <div className="row">
          {job?.running && <span className="muted">{job.label}: {job.done}/{job.total}…</span>}
          <button className="secondary" disabled={!!job?.running} onClick={lookForPhotos}>
            {doc.intake.waiting ? `Look for new photos (${doc.intake.waiting} waiting)` : "Look for new photos"}</button>
          <button disabled={!doc.pending || !!job?.running} onClick={apply}>
            {doc.pending ? `Apply ${doc.pending} change${doc.pending > 1 ? "s" : ""}` : "No changes to apply"}
          </button>
        </div>
      </div>
      <p className="muted small">Every photo, newest activity first. Accepting a photo is a local review step, not an
        approval: it lets the piece be drafted.</p>
      <details className="help"><summary className="small">How to add pieces</summary>
        <p className="muted small">Put one photo per piece in <code>{doc.intake.folder}</code>, then choose
          Look for new photos. Your files aren't changed: each one moves to <code>imported</code> in that folder.</p></details>
      {doc.intake.last && (
        <div className="small intake-last" role="status">
          <p>Last look, {ago(doc.intake.last.at)}: {doc.intake.last.added.length} added, {doc.intake.last.duplicates.length} already here,{" "}
            {doc.intake.last.problems.length} with a problem.{doc.intake.last.left > 0 && ` ${doc.intake.last.left} more waiting: look again.`}</p>
          {doc.intake.last.duplicates.length > 0 && (
            <ul className="muted">{doc.intake.last.duplicates.map((d) => <li key={d.name}>{d.name} is the same file as {d.same_as}</li>)}</ul>)}
          {doc.intake.last.problems.length > 0 && (
            <ul className="warn-text">{doc.intake.last.problems.map((x) => <li key={x.name}>{x.name}: {x.reason}</li>)}</ul>)}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="row between">
        <div className="filters" role="group" aria-label="Stage">
          <button className="chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All <span>{counts.all}</span></button>
          {doc.statuses.filter((s) => counts[s.id]).map((s) => (
            <button key={s.id} className="chip" aria-pressed={filter === s.id} onClick={() => setFilter(s.id)}>
              {s.label} <span>{counts[s.id] || 0}</span>
            </button>
          ))}
        </div>
        <label className="row small sort">Sort
          <select value={order} onChange={(e) => setOrder(e.target.value as Order)}>
            <option value="recent">Latest activity</option><option value="name">File name</option>
          </select>
        </label>
      </div>
      <ul className="grid photo-grid">
        {shown.map((p) => {
          return (
            <li key={p.id} className="card photo-card">
              <a className="photo-open" href={`#/photos/${p.id}`} aria-label={`Open ${p.source}`}>
                {p.image ? <img src={`/${p.image}`} alt="" loading="lazy"
                  style={p.stage === "not-applied" && p.rotate ? { transform: `rotate(${p.rotate}deg)` } : undefined} />
                  : <div className="no-image muted small">{p.error || "No image"}</div>}
              </a>
              <div className="card-body">
                <span className="row between">
                  <a className="small photo-name" href={`#/photos/${p.id}`}>{p.title || p.source}</a>
                  <StatusBadge status={p.status} />
                </span>
                {p.title && <span className="small muted">{p.source}</span>}
                {p.status?.detail && <span className="small">{p.status.detail}</span>}
                {p.crop_flagged && p.stage === "to-review" && (
                  <span className="small warn-text">Crop needs a look{p.crop_reasons[0] ? `: ${p.crop_reasons[0]}` : ""}</span>)}
                <details className="card-history"><summary className="small">History</summary>
                <ol className="timeline" aria-label="History">
                  {p.events.map((e, n) => (
                    <li key={n} title={e.at ? new Date(e.at).toLocaleString() : undefined}>
                      <span>{e.label}</span> <span className="muted">{ago(e.at)}</span>
                    </li>
                  ))}
                </ol></details>
                {p.note && <span className="small muted">Note: {p.note}</span>}
                <div className="row photo-actions">
                  <button className={p.decision === "accept" ? "" : "secondary"} disabled={busy === p.id}
                    aria-pressed={p.decision === "accept"}
                    onClick={() => decide(p, { decision: p.decision === "accept" ? null : "accept" })}>
                    {p.decision === "accept" ? "✓ Accepted" : "Accept"}
                  </button>
                  <button className="secondary" disabled={busy === p.id} title="Turn 90° clockwise; apply to re-frame"
                    onClick={() => decide(p, { rotate: (p.rotate + 90) % 360 })}>Rotate ↻{p.rotate ? ` ${p.rotate}°` : ""}</button>
                  <button className={p.decision === "reject" ? "danger" : "link quiet-danger"} disabled={busy === p.id}
                    aria-pressed={p.decision === "reject"}
                    onClick={() => decide(p, { decision: p.decision === "reject" ? null : "reject" })}>
                    {p.decision === "reject" ? "✗ Rejected" : "Reject"}
                  </button>
                  <a className="small" href={`#/photos/${p.id}`}>{p.kind === "photo" ? "Crop & corners →" : "Details →"}</a>
                  {(p.stage === "drafted" || p.stage === "approved") && <a className="small" href={`#/listings/${p.id}`}>Listing →</a>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {!shown.length && <p className="muted">Nothing here.</p>}
    </main>
  );
}
