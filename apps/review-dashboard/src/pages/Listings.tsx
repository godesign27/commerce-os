import { useMemo, useState } from "react";
import { api, ItemRow, State, StatusId, waitForJob, Job } from "../api";
import { NameSizes } from "../components/NameSizes";
import { StatusBadge } from "../components/Status";

// The status chips show where each piece is. The other views are still here, under More.
type View = "all" | "drafted" | "to-draft" | "approved" | "edited" | "blocking";
type Filter = View | StatusId;
const MORE: Array<[View, string]> = [["drafted", "All drafted"], ["to-draft", "Not drafted"], ["approved", "Copy approved"],
  ["edited", "Edited, not approved"], ["blocking", "Facts to supply in the draft"]];
const VIEWS: Record<View, (i: ItemRow) => boolean> = {
  all: () => true, drafted: (i) => i.drafted, "to-draft": (i) => !i.drafted, approved: (i) => i.approved,
  edited: (i) => i.edited && !i.approved, blocking: (i) => i.blocking > 0,
};

export function Listings({ state, onChange }: { state: State; onChange: () => void }) {
  const [filter, setFilter] = useState<Filter>("drafted");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());   // pieces ticked to draft (B-081)
  const items = useMemo(() => state.items.filter((i) => i.has_art && i.crop_decision !== "reject"), [state.items]);
  const test = (i: ItemRow, f: Filter) => (f in VIEWS ? VIEWS[f as View](i) : i.status.id === f);
  const shown = items.filter((i) => test(i, filter));
  const toDraft = items.filter((i) => !i.drafted).length;
  const ticked = items.filter((i) => !i.drafted && picked.has(i.id)).map((i) => i.id);
  const shownUndrafted = shown.filter((i) => !i.drafted);
  const allShownTicked = shownUndrafted.length > 0 && shownUndrafted.every((i) => picked.has(i.id));
  const busy = !!job?.running;

  function toggle(id: string) {
    setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  function tickShown() {
    setPicked((p) => { const n = new Set(p); shownUndrafted.forEach((i) => (allShownTicked ? n.delete(i.id) : n.add(i.id))); return n; });
  }
  async function draft(n: number | string[]) {
    setError(null);
    try {
      const { job: id } = typeof n === "number" ? await api.draftPending(n) : await api.draftSelected(n);
      await waitForJob(id, setJob);
      if (typeof n !== "number") setPicked(new Set());
      onChange();
    } catch (e) { setError(String((e as Error).message)); }
  }

  const statuses = state.statuses.filter((s) => items.some((i) => i.status.id === s.id));
  return (
    <main className="page">
      <div className="row between page-head">
        <h1>Listings</h1>
        <div className="row">
          {job?.running && <span className="muted">{job.label}: {job.done}/{job.total}…</span>}
          {job && !job.running && <span className="muted">Done · ${job.cost_usd.toFixed(2)}{job.error ? ` · ${job.error}` : ""}</span>}
          <NameSizes onSaved={onChange} />
          {ticked.length > 0 && <button className="secondary" disabled={busy} onClick={() => setPicked(new Set())}>Clear</button>}
          {ticked.length > 0
            ? <button disabled={!state.key_configured || busy} onClick={() => draft(ticked)}>Draft {ticked.length} selected</button>
            : <button disabled={!state.key_configured || !toDraft || busy} onClick={() => draft(5)}>Draft next {Math.min(5, toDraft)}</button>}
        </div>
      </div>
      {toDraft > 0 && (
        <p className="small muted draft-help">
          {state.key_configured
            ? <>Tick the pieces you want drafted, then press Draft selected. Draft next {Math.min(5, toDraft)} takes the first pieces in the list instead.</>
            : <>Add your Claude API key on Getting started to draft listings.</>}
          {shownUndrafted.length > 0 && <>{" "}<button type="button" className="link" disabled={busy} onClick={tickShown}>
            {allShownTicked ? "Untick" : "Tick"} all {shownUndrafted.length} shown</button></>}
        </p>)}
      {error && <p className="error">{error}</p>}
      <div className="row between filter-row">
        <div className="filters" role="group" aria-label="Status">
          <button className="chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All <span>{items.length}</span></button>
          {statuses.map((s) => (
            <button key={s.id} className="chip" aria-pressed={filter === s.id} onClick={() => setFilter(s.id)}>
              {s.label} <span>{items.filter((i) => i.status.id === s.id).length}</span>
            </button>
          ))}
        </div>
        <label className="row small sort">More
          <select value={MORE.some(([k]) => k === filter) ? filter : ""} onChange={(e) => e.target.value && setFilter(e.target.value as View)}>
            <option value="">Choose a view</option>
            {MORE.map(([k, label]) => <option key={k} value={k}>{label} ({items.filter((i) => VIEWS[k](i)).length})</option>)}
          </select>
        </label>
      </div>
      <ul className="grid">
        {shown.map((i) => (
          <li key={i.id} className={!i.drafted ? "pickable" : undefined}>
            {!i.drafted && (
              <label className={`card-pick ${picked.has(i.id) ? "on" : ""}`}>
                <input type="checkbox" checked={picked.has(i.id)} disabled={busy} onChange={() => toggle(i.id)}
                       aria-label={`Draft ${i.source}`} />
              </label>)}
            <a className={`card ${i.status.id === "published" ? "is-published" : ""} ${picked.has(i.id) && !i.drafted ? "is-picked" : ""}`} href={`#/listings/${i.id}`}>
              {i.image && <img src={`/${i.image}`} alt="" loading="lazy" />}
              <div className="card-body">
                <strong>{i.title || <span className="muted">Not drafted</span>}</strong>
                <span className="muted small">{i.source}</span>
                <span className="card-status"><StatusBadge status={i.status} />
                  {i.status.detail && <span className="small">{i.status.detail}</span>}</span>
                <span className="card-meta small muted">
                  {i.drafted && <span title="The draft's revision">Revision {i.revision}</span>}
                  {i.edited && !i.approved && <span>Edited</span>}
                  {i.blocking > 0 && <span className="warn-text">{i.blocking} to supply</span>}
                  {i.supplied > 0 && <span title="Supplied since this draft: redraft to use it in the copy">{i.supplied} supplied · redraft</span>}
                  {i.warnings > 0 && <span className="warn-text">{i.warnings} check{i.warnings === 1 ? "" : "s"}</span>}
                </span>
              </div>
            </a>
          </li>
        ))}
      </ul>
      {!shown.length && <p className="muted">Nothing here.</p>}
    </main>
  );
}
