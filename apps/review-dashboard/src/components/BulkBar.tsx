import { useState } from "react";
import { api, BulkResult, BulkSkip, ItemRow, StoreRow } from "../api";

// What to do with the pieces ticked on the Listings page (B-087). Each action shows how many ticked pieces it
// suits; the server applies each piece's own rules and says which it skipped and why. Approving for the store
// first shows exactly what each piece would send, and approves those versions only, as the Publish page does.
const COST_LOW = 0.08, COST_HIGH = 0.12;      // one drafting call, as the drafting script quotes it
type Mode = null | "facts" | "store" | "redraft";

function money(p: StoreRow["price"]) {
  return p ? (p.amount_minor / 100).toLocaleString("en-US", { style: "currency", currency: p.currency }) : null;
}

export function BulkBar({ ticked, tierTypes, keyConfigured, busy, onDraft, onJob, onDone, onClear }: {
  ticked: ItemRow[]; tierTypes: string[]; keyConfigured: boolean; busy: boolean;
  onDraft: (ids: string[]) => void; onJob: (job: string) => Promise<void>; onDone: () => void; onClear: () => void;
}) {
  const [mode, setMode] = useState<Mode>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState<{ text: string; skipped: BulkSkip[] } | null>(null);
  const [rows, setRows] = useState<StoreRow[] | null>(null);
  const [facts, setFacts] = useState({ medium: "", dimensions: "", price: "", sold_as: "", edition: "" });
  const [overwrite, setOverwrite] = useState(false);

  const undrafted = ticked.filter((i) => !i.drafted);
  const open = ticked.filter((i) => i.drafted && !i.approved);       // drafted, copy not yet approved
  const drafted = ticked.filter((i) => i.drafted);
  const off = busy || working;
  const ids = (xs: ItemRow[]) => xs.map((i) => i.id);
  const given = Object.values(facts).some((v) => v.trim());

  async function run(fn: () => Promise<BulkResult>, verb: string) {
    setWorking(true); setError(null); setSaid(null);
    try {
      const r = await fn();
      setSaid({ text: `${verb} ${r.done.length} piece${r.done.length === 1 ? "" : "s"}.`, skipped: r.skipped });
      setMode(null); setRows(null);
      if (r.job) await onJob(r.job);
      onDone();
    } catch (e) { setError(String((e as Error).message)); }
    setWorking(false);
  }

  async function showStore() {
    setMode("store"); setRows(null); setWorking(true); setError(null); setSaid(null);
    try {
      const r = await api.bulk("store_preview", { ids: ids(drafted) });
      setRows(r.rows || []);
      setSaid(r.skipped.length ? { text: "", skipped: r.skipped } : null);
    } catch (e) { setError(String((e as Error).message)); setMode(null); }
    setWorking(false);
  }

  const clean = Object.fromEntries(Object.entries(facts).filter(([, v]) => v.trim()));
  return (
    <section className="bulk-bar" aria-label="Selected listings">
      <div className="row bulk-actions">
        <strong>{ticked.length} selected</strong>
        {undrafted.length > 0 && <button disabled={off || !keyConfigured} onClick={() => onDraft(ids(undrafted))}>Draft {undrafted.length} selected</button>}
        {open.length > 0 && <button disabled={off} onClick={() => run(() => api.bulk("approve_copy", { ids: ids(open) }), "Approved the copy of")}>Approve copy ({open.length})</button>}
        <button className="secondary" disabled={off} aria-expanded={mode === "facts"} onClick={() => setMode(mode === "facts" ? null : "facts")}>Supply details…</button>
        {drafted.length > 0 && <button className="secondary" disabled={off} aria-expanded={mode === "store"} onClick={() => (mode === "store" ? setMode(null) : showStore())}>Approve for store…</button>}
        {open.length > 0 && <button className="secondary" disabled={off || !keyConfigured} aria-expanded={mode === "redraft"} onClick={() => setMode(mode === "redraft" ? null : "redraft")}>Redraft…</button>}
        <button className="link" disabled={off} onClick={() => { setMode(null); setSaid(null); onClear(); }}>Clear</button>
      </div>

      {mode === "facts" && (
        <div className="bulk-panel">
          <p className="small muted">Fill in what's the same for all {ticked.length}. Blank fields are left alone. These go to the store only; they never change the copy.</p>
          <div className="bulk-fields">
            <label>Medium<input value={facts.medium} placeholder="e.g. acrylic on canvas" onChange={(e) => setFacts({ ...facts, medium: e.target.value })} /></label>
            <label>Size<input value={facts.dimensions} placeholder="e.g. 16 x 20 in" onChange={(e) => setFacts({ ...facts, dimensions: e.target.value })} /></label>
            <label>Price (US dollars)<input inputMode="decimal" value={facts.price} placeholder="e.g. 450" onChange={(e) => setFacts({ ...facts, price: e.target.value })} /></label>
            <label>Sold as<select value={facts.sold_as} onChange={(e) => setFacts({ ...facts, sold_as: e.target.value })}>
              <option value="">Leave as is</option>{tierTypes.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
            <label>Edition<select value={facts.edition} onChange={(e) => setFacts({ ...facts, edition: e.target.value })}>
              <option value="">Leave as is</option><option value="original">Original</option><option value="print">Print</option><option value="both">Original and prints</option></select></label>
          </div>
          <label className="small bulk-replace"><input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> Replace details a piece already has (otherwise only empty ones are filled)</label>
          <div className="row section-actions">
            <button disabled={off || !given} onClick={() => run(() => api.bulk("facts", { ids: ids(ticked), facts: clean, overwrite }), "Saved details for")}>Apply to {ticked.length}</button>
            <button className="secondary" disabled={off} onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>)}

      {mode === "store" && (
        <div className="bulk-panel">
          {!rows ? <p className="small muted">Checking what each piece would send…</p> : rows.length === 0
            ? <p className="small">None of the ticked pieces can be approved for the store yet.</p>
            : <>
              <p className="small muted">What each piece would send. Approving records these exact versions; nothing goes to the store until you publish.</p>
              <ul className="bulk-store">
                {rows.map((r) => (
                  <li key={r.id}><strong>{r.title}</strong>{" "}
                    {r.update
                      ? <span className="small"><span className="badge">Update</span> {r.changes.join(", ")}</span>
                      : <span className="small muted">New Draft · {[r.sold_as, money(r.price), r.size].filter(Boolean).join(" · ")}</span>}
                  </li>))}
              </ul>
              <div className="row section-actions">
                <button disabled={off} onClick={() => run(() => api.bulk("approve_store", { items: rows.map((r) => ({ id: r.id, change_set_hash: r.change_set_hash })) }), "Approved for the store:")}>
                  Approve {rows.length} for the store</button>
                <button className="secondary" disabled={off} onClick={() => { setMode(null); setRows(null); }}>Cancel</button>
              </div>
            </>}
        </div>)}

      {mode === "redraft" && (
        <div className="bulk-panel">
          <p className="small">Redraft {open.length}: one Claude call each, about ${(open.length * COST_LOW).toFixed(2)}–${(open.length * COST_HIGH).toFixed(2)} in all.
            Each gets a new draft, and edits you haven't approved are replaced. Pieces with approved copy are left alone.</p>
          <div className="row section-actions">
            <button disabled={off} onClick={() => run(() => api.bulk("redraft", { ids: ids(open) }), "Redrafted")}>Redraft {open.length}</button>
            <button className="secondary" disabled={off} onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>)}

      {error && <p className="error small">{error}</p>}
      {said && (
        <div className="small" role="status">
          {said.text && <p>{said.text}</p>}
          {said.skipped.length > 0 && <>
            <p className="warn-text">Skipped {said.skipped.length}:</p>
            <ul>{said.skipped.map((s) => <li key={s.id}><strong>{s.title}</strong>: {s.reason}</li>)}</ul>
          </>}
        </div>)}
    </section>
  );
}
