import { useCallback, useEffect, useState } from "react";
import { api, PreviewRow, StorefrontPreview } from "../api";

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

  async function approve() {
    if (!p?.change_set) return;
    setBusy(true); setError(null);
    try { setP(await api.approveStorefront(id, p.change_set.change_set_hash, p.change_set.requested_status)); onChange(); }
    catch (e) { setError(String((e as Error).message)); await load(); }
    setBusy(false);
  }

  if (!p) return error ? <p className="error">{error}</p> : null;
  const name = p.display_name || "the store";
  if (!p.available) return <section className="panel storefront"><h2>{name}</h2><p className="muted small">{p.reason}</p></section>;
  const blocking = (p.blockers || []).filter((b) => b.severity === "blocking" && b.target !== AFTER_APPROVAL);
  const warnings = (p.blockers || []).filter((b) => b.severity === "warning");
  const delivery = (p.blockers || []).find((b) => b.target === AFTER_APPROVAL);
  const a = p.approval!;
  const status = STATUS_WORDS[p.change_set!.requested_status] || p.change_set!.requested_status;

  return (
    <section className={`panel storefront ${a.state === "out_of_date" ? "dirty" : a.state === "current" ? "is-ready" : ""}`} aria-labelledby={`sf-${id}`}>
      <h2 id={`sf-${id}`}>{name}{" "}
        {a.state === "current" ? <span className="badge ok">✓ Approved</span>
          : a.state === "out_of_date" ? <span className="badge bad">Approval out of date</span>
          : p.approvable ? <span className="badge">Ready to approve</span>
          : <span className="badge bad">{blocking.length} to resolve</span>}</h2>
      <p className="muted small">What {name} would receive for this piece, as a new product. This is a preview against a
        test copy of the store: nothing is sent, and publishing comes in a later phase.</p>

      {blocking.length > 0 && (
        <div className="sf-block"><h3 className="small">Before you can approve it</h3>
          <ul>{blocking.map((b) => <li key={b.id}>{b.question}</li>)}</ul></div>
      )}
      {(warnings.length > 0 || (p.notes || []).length > 0) && (
        <ul className="small sf-warn">{warnings.map((w) => <li key={w.id}>{w.question}</li>)}
          {(p.notes || []).map((n) => <li key={n}>{n}</li>)}</ul>
      )}

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
