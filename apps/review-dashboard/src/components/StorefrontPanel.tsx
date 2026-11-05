import { useCallback, useEffect, useState } from "react";
import { api, MatchCandidate, PreviewRow, StorefrontPreview, waitForJob } from "../api";

// What the storefront would receive for this listing, field by field, and the owner's approval of exactly that
// (Gate 3, B-064). It runs against the test copy of the store: nothing is sent anywhere. The approval names the
// change set's hash; any later change to the copy, a fact, an image or the store mapping puts it out of date.
const EVIDENCE: Record<string, string> = {
  supplied: "you supplied it", human_confirmed: "you approved it", inferred: "drafted", observed: "from the photo",
  verified_catalog: "from the store",
};
const STATUS_WORDS: Record<string, string> = { draft: "Draft (hidden until you set it live)", active: "Live", archived: "Archived" };
const AFTER_APPROVAL = "assets.delivery";      // copied from packages/adapters/artstore_map.py (AFTER_APPROVAL)

function money(v: unknown) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD" }) : String(v);
}

function show(r: PreviewRow): string {
  const v = r.display;
  if (r.column === "price") return money(v);
  if (r.column === "status") return STATUS_WORDS[String(v)] || String(v);
  if (r.column === "pricing_tiers" && Array.isArray(v))
    return v.map((t: { type: string; price: number; size?: string }) => [t.type, money(t.price), t.size].filter(Boolean).join(" · ")).join("; ");
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "None";
  if (v === "" || v == null) return "Empty";
  return String(v);
}

export function StorefrontPanel({ id, version, onChange }: { id: string; version: string; onChange: () => void }) {
  const [p, setP] = useState<StorefrontPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);
  const load = useCallback(() => api.storefront(id).then(setP).catch((e) => setError(String(e.message))), [id]);
  useEffect(() => { load(); }, [load, version]);
  // While the worker has it, or it's being checked, keep looking.
  const active = p?.publish && (p.publish.state === "QUEUED" || p.publish.state === "WRITING" || p.publish.checking);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
  }, [active, load]);

  async function approve() {
    if (!p?.change_set) return;
    setBusy(true); setError(null);
    try { setP(await api.approveStorefront(id, p.change_set.change_set_hash, p.change_set.requested_status)); onChange(); }
    catch (e) { setError(String((e as Error).message)); await load(); }
    setBusy(false);
  }

  async function readCatalog() {
    setBusy(true); setError(null);
    try {
      const { job } = await api.refreshCatalog();
      const j = await waitForJob(job);
      if (j.error) setError(j.error);
      await load(); onChange();
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }

  async function answer(c: MatchCandidate, value: "same" | "different" | null) {
    setBusy(true); setError(null);
    try { setP(await api.answerMatch(id, c.product_id, value)); onChange(); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }

  async function run(fn: () => Promise<StorefrontPreview>) {
    setBusy(true); setError(null);
    try { setP(await fn()); onChange(); }
    catch (e) { setError(String((e as Error).message)); await load(); }
    setBusy(false);
  }

  async function switchWriting(on: boolean) {
    setBusy(true); setError(null);
    try { await api.killSwitch(on); await load(); onChange(); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }

  if (!p) return error ? <p className="error">{error}</p> : null;
  const name = p.display_name || "the store";
  if (!p.available) return <section className="panel storefront"><h2>{name}</h2><p className="muted small">{p.reason}</p></section>;
  const blocking = (p.blockers || []).filter((b) => b.severity === "blocking" && b.target !== AFTER_APPROVAL);
  const warnings = (p.blockers || []).filter((b) => b.severity === "warning");
  const delivery = (p.blockers || []).find((b) => b.target === AFTER_APPROVAL);
  const a = p.approval!;
  const pub = p.publish;
  const status = STATUS_WORDS[p.change_set!.requested_status] || p.change_set!.requested_status;

  return (
    <section className={`panel storefront ${a.state === "out_of_date" ? "dirty" : a.state === "current" ? "is-ready" : ""}`} aria-labelledby={`sf-${id}`}>
      <h2 id={`sf-${id}`}>{name}{" "}
        {a.state === "current" ? <span className="badge ok">✓ Approved</span>
          : a.state === "out_of_date" ? <span className="badge bad">Approval out of date</span>
          : p.approvable ? <span className="badge">Ready to approve</span>
          : <span className="badge bad">{blocking.length} to resolve</span>}</h2>
      <p className="muted small">What this piece would become, as a new hidden product. For now it can only be published
        to a local test store on this computer: {name} itself can't be changed.</p>

      {blocking.length > 0 && (
        <div className="sf-block"><h3 className="small">Before you can approve it</h3>
          <ul>{blocking.map((b) => <li key={b.id}>{b.question}</li>)}</ul></div>
      )}
      {(warnings.length > 0 || (p.notes || []).length > 0) && (
        <ul className="small sf-warn">{warnings.map((w) => <li key={w.id}>{w.question}</li>)}
          {(p.notes || []).map((n) => <li key={n}>{n}</li>)}</ul>
      )}

      <div className="sf-catalog">
        <h3 className="small">Already in the store?</h3>
        <p className="muted small">
          {p.catalog?.read_at
            ? `Checked against a copy of ${name}'s catalog read ${new Date(p.catalog.read_at).toLocaleString()} (${p.catalog.products} products). `
            : `Not checked yet: ${name}'s catalog hasn't been read. `}
          Reading it changes nothing in the store.{" "}
          <button className="link" disabled={busy} onClick={readCatalog}>{p.catalog?.read_at ? "Read it again" : "Read the catalog"}</button>
        </p>
        {p.catalog?.read_at && !p.catalog.candidates.length && <p className="muted small">Nothing there looks like this piece.</p>}
        {(p.catalog?.candidates.length || 0) > 0 && (
          <ul className="sf-matches">
            {p.catalog!.candidates.map((c) => (
              <li key={c.product_id}>
                <strong>{c.name || "Untitled"}</strong>{" "}
                <span className={`badge ${c.level === "likely" && !c.answer ? "bad" : ""}`}>{c.level === "likely" ? "Looks like this piece" : "Possibly related"}</span>
                <span className="muted small"> {[c.medium, c.dimensions, c.status].filter(Boolean).join(" · ")}</span>
                <ul className="small">
                  {c.matching.map((m) => <li key={m}>{m}</li>)}
                  {c.conflicting.map((m) => <li key={m} className="warn-text">{m}</li>)}
                </ul>
                <div className="row">
                  <span className="small">Same piece?</span>
                  <button className={c.answer === "same" ? "" : "secondary"} aria-pressed={c.answer === "same"} disabled={busy}
                    onClick={() => answer(c, c.answer === "same" ? null : "same")}>Same piece</button>
                  <button className={c.answer === "different" ? "" : "secondary"} aria-pressed={c.answer === "different"} disabled={busy}
                    onClick={() => answer(c, c.answer === "different" ? null : "different")}>Different piece</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <table className="sf-table">
        <tbody>
          {(p.rows || []).filter((r) => r.column !== "id").map((r) => (
            <tr key={r.column}>
              <th scope="row">{r.label}</th>
              <td>{r.column === "images"
                ? <span className="sf-images">{(p.images || []).map((im) => <img key={im.kind} src={`/${im.image}`} alt={im.kind === "room" ? "Room view" : "Framed image"} />)}
                    {!(p.images || []).length && "None"}</span>
                : <span className={r.column === "description" || r.column === "short_description" ? "sf-long" : ""}>{show(r)}</span>}
                <span className="muted small sf-ev"> {EVIDENCE[r.evidence] || r.evidence}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Left as the store has them: {p.change_set!.not_touched.join(", ")}.</p>
      {delivery && <p className="small muted">Images: {delivery.question}</p>}

      {a.state === "current" && a.approval && (
        <p className="banner ok small">Approved {new Date(a.approval.approved_at).toLocaleString()} as {status}. Change set {a.approval.change_set_hash.slice(0, 12)}.</p>
      )}
      {a.state === "out_of_date" && a.approval && (
        <p className="small warn-text" role="status">Approved {new Date(a.approval.approved_at).toLocaleString()}, but since then
          these changed: {a.changes.join(", ")}. That approval no longer counts; approve this version to replace it.</p>
      )}
      {a.state !== "current" && (
        <div className="row section-actions">
          <button disabled={!p.approvable || busy} onClick={approve}>
            {busy ? "Approving…" : `${a.state === "out_of_date" ? "Approve this version" : `Approve for ${name}`} as Draft`}</button>
          {!p.approvable && <span className="muted small">Resolve the items above first.</span>}
        </div>
      )}
      {a.state === "current" && p.publish && (
        <div className="sf-publish" role="status">
          <h3 className="small">Publish</h3>
          {pub!.state === null && <p className="small muted">This listing is on the <a href="#/publish">Publish page</a> with everything else that's ready, or you can publish just this one here.</p>}
          {pub!.kill_switch.on && <p className="banner small">Writing is switched off{pub!.kill_switch.forced ? ` by ${pub!.kill_switch.by}` : ""}, so nothing can be published.</p>}
          {!pub!.worker.running && <p className="small warn-text">The publishing worker isn't running, so a publish will wait. Start Commerce OS with ./start.sh.</p>}
          {pub!.worker.running && !pub!.worker.ok && pub!.worker.reason && <p className="small warn-text">{pub!.worker.reason}</p>}

          {(pub!.state === "QUEUED" || pub!.state === "WRITING") && <p className="small">{pub!.state === "QUEUED" ? "Queued: the worker will run its final check." : "Publishing…"}</p>}
          {pub!.state === "SUCCEEDED" && (
            <p className="banner ok small">Published to the {pub!.target.toLowerCase()} as a hidden draft, and confirmed by reading it back.
              Product {pub!.product_id}, receipt {pub!.receipt_id}. {name} itself hasn't changed.</p>)}
          {pub!.state === "FAILED" && (
            <div className="small"><p className="error">Not published. Nothing went into the store.</p>
              <ul>{pub!.reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>)}
          {pub!.state === "OUTCOME_UNKNOWN" && (
            <div className="small warn-text">
              {pub!.finding === "mismatch"
                ? <p>The store has this product, but it doesn't match what you approved ({pub!.fields.join(", ")}). Nothing will overwrite it: this needs your decision.</p>
                : <p>The result of the publish wasn't seen, so it may or may not have gone in. Publishing again could add it twice, so check the store first.{pub!.finding === "not_found" ? " It wasn't there at the last check; one more check a minute later settles it." : ""}</p>}
              <button className="secondary" disabled={busy || pub!.checking} onClick={() => run(() => api.publishRecheck(id))}>{pub!.checking ? "Checking…" : "Check again"}</button>
            </div>)}
          {(pub!.state === null || pub!.state === "FAILED") && (
            <div className="row section-actions">
              <button disabled={busy || pub!.kill_switch.on} onClick={() => run(() => api.publish(id, p.change_set!.change_set_hash))}>
                {pub!.state === "FAILED" ? "Publish again" : "Publish"} to {pub!.target.toLowerCase()}</button>
            </div>)}
          {!pub!.kill_switch.forced && (
            <button className="link" disabled={busy} onClick={() => switchWriting(!pub!.kill_switch.on)}>
              {pub!.kill_switch.on ? "Switch writing back on" : "Stop all writing"}</button>)}
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <button className="link" aria-expanded={history} onClick={() => setHistory(!history)}>{history ? "Hide" : "Show"} history ({p.history.length})</button>
      {history && (
        <ol className="timeline small">
          {p.history.map((e, i) => (
            <li key={i}><span className="muted">{e.at ? new Date(e.at).toLocaleString() : "time not recorded"}</span> {e.label}</li>
          ))}
        </ol>
      )}
    </section>
  );
}
