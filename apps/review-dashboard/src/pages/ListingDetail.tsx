import { ReactNode, useCallback, useEffect, useState } from "react";
import { api, Check, Copy, Detail, Draft, Field, Issue, Job, State, StorefrontPreview, waitForJob } from "../api";
import { AboutPiece } from "../components/AboutPiece";
import { StorefrontPanel } from "../components/StorefrontPanel";
import { StatusBadge, Tracker } from "../components/Status";

const wordCount = (s: string) => (s.match(/[A-Za-z0-9']+/g) || []).length;
const splitList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const FIELDS: Field[] = ["title", "short_description", "collector_description", "store_tags", "search_keywords"];
const LABELS: Record<Field, string> = {
  title: "Title", short_description: "Short description", collector_description: "Collector description",
  store_tags: "Store tags", search_keywords: "Search keywords",
};
const OTHER = "__other__";
type Local = Record<Field, string>;
const toLocal = (c: Copy): Local => ({
  title: c.title, short_description: c.short_description, collector_description: c.collector_description,
  store_tags: c.store_tags.join(", "), search_keywords: c.search_keywords.join(", "),
});
const RUBRIC_LABELS: Record<string, string> = {
  brand_alignment: "Brand alignment", visual_specificity: "Visual specificity",
  interpretive_restraint: "Interpretive restraint", distinctiveness: "Distinctiveness",
  collector_appeal: "Collector appeal", human_story: "Human story", catalog_readiness: "Catalog readiness",
};

export function ListingDetail({ id, state, onChange }: { id: string; state: State; onChange: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [copy, setCopy] = useState<Copy | null>(null);
  const [local, setLocal] = useState<Local | null>(null);
  const [titleChoice, setTitleChoice] = useState<string>("");
  const [checks, setChecks] = useState<Partial<Record<Field, Check[]>>>({});
  const [busy, setBusy] = useState<Field | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDraft, setShowDraft] = useState(false);
  const [storeRev, setStoreRev] = useState(0);        // the next-step bar approved or published: the store panel reads again

  const load = useCallback(() => api.item(id).then((x) => {
    setD(x);
    const c = x.draft ? x.draft.effective : null;
    setCopy(c);
    setLocal(c ? toLocal(c) : null);
    setChecks({});
    const opts = x.draft?.title_options.map((o) => o.title) || [];
    setTitleChoice(c && opts.includes(c.title) ? c.title : OTHER);
  }), [id]);
  useEffect(() => { load().catch((e) => setError(String(e.message))); }, [load]);
  // Only the status: an approval or publish lower down must not throw away copy being edited.
  const refreshStatus = useCallback(() => api.item(id).then((x) => setD((p) => p && { ...p, status: x.status })).catch(() => undefined), [id]);

  const locked = !!d?.listing.approved;
  const ids = state.items.filter((i) => i.drafted).map((i) => i.id);
  const pos = ids.indexOf(id);
  const dirty = (k: Field) => !!(copy && local && local[k] !== toLocal(copy)[k]);
  const unsaved = FIELDS.filter(dirty);

  // warn before the tab closes with unsaved sections
  useEffect(() => {
    if (!unsaved.length) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [unsaved.length]);

  function leaveOk() {
    return !unsaved.length || window.confirm(`You have unsaved changes in: ${unsaved.map((k) => LABELS[k].toLowerCase()).join(", ")}. Discard them?`);
  }
  function setField(k: Field, v: string) { if (local) { setLocal({ ...local, [k]: v }); setChecks({ ...checks, [k]: undefined }); } }

  async function saveField(k: Field, value: string | null) {
    setError(null);
    if (k === "title" && value !== null && !value.trim()) { setError("Write a title first."); return; }
    setBusy(k);
    try {
      const body = value === null ? null : (k === "store_tags" || k === "search_keywords") ? splitList(value) : value;
      const res = await api.saveCopy(id, { [k]: body });
      setCopy(res.copy);
      setLocal({ ...local!, [k]: toLocal(res.copy)[k] });
      if (k === "title") {
        const opts = d?.draft?.title_options.map((o) => o.title) || [];
        setTitleChoice(opts.includes(res.copy.title) ? res.copy.title : OTHER);
      }
      setChecks({ ...checks, [k]: res.checks.filter((c) => c.field === k) });
      onChange();
    } catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(null); }
  }
  function discard(k: Field) {
    if (!copy || !local) return;
    setLocal({ ...local, [k]: toLocal(copy)[k] });
    if (k === "title") {
      const opts = d?.draft?.title_options.map((o) => o.title) || [];
      setTitleChoice(opts.includes(copy.title) ? copy.title : OTHER);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); await load(); onChange(); } catch (e) { setError(String((e as Error).message)); }
  }
  async function redraft() {
    if (!leaveOk()) return;
    await act(async () => { const { job: j } = await api.redraft(id); const done = await waitForJob(j, setJob); if (done.error) throw new Error(done.error); });
  }

  if (error && !d) return <main className="page"><p className="error">{error}</p></main>;
  if (!d) return <main className="page"><p className="muted">Loading…</p></main>;
  const dr = d.draft;
  const lim = { short: [18, 35], long: [85, 135] };

  return (
    <main className="page detail">
      <div className="row between detail-nav">
        <div className="row">
          <a href="#/listings" onClick={(e) => { if (!leaveOk()) e.preventDefault(); }}>← Listings</a>
          {pos > 0 && <a href={`#/listings/${ids[pos - 1]}`} onClick={(e) => { if (!leaveOk()) e.preventDefault(); }}>Previous</a>}
          {pos >= 0 && pos < ids.length - 1 && <a href={`#/listings/${ids[pos + 1]}`} onClick={(e) => { if (!leaveOk()) e.preventDefault(); }}>Next</a>}
          {pos >= 0 && <span className="muted small">{pos + 1} of {ids.length} drafted</span>}
        </div>
        <div className="row">
          {unsaved.length > 0 && !locked && <span className="small unsaved-note">{unsaved.length} unsaved section{unsaved.length > 1 ? "s" : ""}</span>}
          {job?.running && <span className="muted">Drafting… (about a minute)</span>}
          {dr && !locked && <button className="secondary" disabled={!state.key_configured || !!job?.running} onClick={redraft}>Redraft with my note</button>}
          {locked && <button className="secondary" onClick={() => act(() => api.unlock(id))}>Unlock to edit</button>}
        </div>
      </div>
      <div className="detail-head">
        <h1>{copy?.title || d.item.source} <StatusBadge status={d.status} /></h1>
        <Tracker status={d.status} pipeline={d.pipeline} />
      </div>
      {/* Under the progress, so the details for each piece are filled in without scrolling (B-090). */}
      <AboutPiece key={d.item.id} itemId={d.item.id} series={d.listing.series || ""} facts={d.listing.facts || {}} sizeFromName={d.size_from_name} tierTypes={d.tier_types} wide
                      note={dr ? "Redraft to use it in the copy." : undefined} onSaved={async () => { await load(); onChange(); }} />

      <NextStep d={d} approve={dr && !locked ? () => { if (leaveOk()) act(() => api.approve(id)); } : null}
                onStore={async () => { await refreshStatus(); setStoreRev((n) => n + 1); onChange(); }} />
      {error && <p className="error">{error}</p>}

      <div className="two-col">
        <section className="art">
          {d.image && <img src={`/${d.image}`} alt={copy?.title || d.item.source} />}
          <details className="draft-info" open={!!dr && dr.issues.some((i) => i.severity === "blocking" && !d.listing.facts?.[i.target === "product.material" ? "medium" : "dimensions"])}>
            <summary>How this was drafted</summary>
            <p className="muted small">{d.item.source}{dr ? ` · revision ${dr.revision} · ${dr.model}${dr.cost_usd != null ? ` · $${dr.cost_usd.toFixed(3)}` : ""}` : ""}</p>
            {dr?.brand_context && <p className="muted small">Voice: {dr.brand_context} · {dr.prompt}{dr.inputs.edit_pairs ? " · used your past edits" : ""}</p>}
            {dr && <ReviewTabs dr={dr} facts={d.listing.facts || {}} />}
          </details>
        </section>

        <section className="copy">
          {!dr && <p className="muted">Not drafted yet. Use “Draft next” on the Listings page, or add a note first.</p>}
          {dr && copy && (
            <>
              {locked && <p className="banner ok">Approved {new Date(d.listing.approved!.at).toLocaleString()}. Unlock to change it.</p>}
              {dr.moment && (
                <p className="moment"><span className={`badge ${dr.moment.basis === "confirmed" ? "ok" : "warn"}`}>{dr.moment.basis === "confirmed" ? "Confirmed" : "Proposed"}</span> {dr.moment.text}</p>
              )}
              {local && (<>
              <Section label="Title" dirty={dirty("title")} edited={copy.title !== undefined && JSON.stringify(copy.title) !== JSON.stringify(dr.proposed.title)} locked={locked} busy={busy === "title"} checks={checks["title"]}
                onSave={() => saveField("title", local!["title"])} onDiscard={() => discard("title")} onRevert={() => saveField("title", null)}>
                <div className="options" role="radiogroup" aria-label="Title">
                  {dr.title_options.map((o) => (
                    <label key={o.title} className={`option ${titleChoice === o.title ? "on" : ""}`}>
                      <input type="radio" name="title" checked={titleChoice === o.title}
                        onChange={() => { setTitleChoice(o.title); setField("title", o.title); }} />
                      <span><strong>{o.title}</strong>{o.title === dr.proposed.title && <span className="badge">Recommended</span>}<br />
                        <span className="muted small">{o.angle}: {o.rationale}</span></span>
                    </label>
                  ))}
                  <label className={`option ${titleChoice === OTHER ? "on" : ""}`}>
                    <input type="radio" name="title" checked={titleChoice === OTHER}
                      onChange={() => { setTitleChoice(OTHER); if (dr.title_options.some((o) => o.title === local.title)) setField("title", ""); }} />
                    <span><strong>Other</strong><br /><span className="muted small">Write your own title.</span>
                      {titleChoice === OTHER && (
                        <input aria-label="Your title" className="other-title" autoFocus={!local.title} value={local.title} placeholder="Your title"
                          onChange={(e) => setField("title", e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter" && dirty("title") && local.title.trim()) saveField("title", local.title); }} />
                      )}
                    </span>
                  </label>
                </div>
                {dr.title_reason && <p className="muted small">Why the recommendation: {dr.title_reason}</p>}
              </Section>

              <Section label="Short description" extra={<Count n={wordCount(local.short_description)} range={lim.short} chars={local.short_description.length} max={200} />} dirty={dirty("short_description")} edited={copy.short_description !== undefined && JSON.stringify(copy.short_description) !== JSON.stringify(dr.proposed.short_description)} locked={locked} busy={busy === "short_description"} checks={checks["short_description"]}
                onSave={() => saveField("short_description", local!["short_description"])} onDiscard={() => discard("short_description")} onRevert={() => saveField("short_description", null)}>
                <textarea rows={3} value={local.short_description} onChange={(e) => setField("short_description", e.target.value)} />
              </Section>
              <Section label="Collector description" extra={<Count n={wordCount(local.collector_description)} range={lim.long} />} dirty={dirty("collector_description")} edited={copy.collector_description !== undefined && JSON.stringify(copy.collector_description) !== JSON.stringify(dr.proposed.collector_description)} locked={locked} busy={busy === "collector_description"} checks={checks["collector_description"]}
                onSave={() => saveField("collector_description", local!["collector_description"])} onDiscard={() => discard("collector_description")} onRevert={() => saveField("collector_description", null)}>
                <textarea rows={9} value={local.collector_description} onChange={(e) => setField("collector_description", e.target.value)} />
              </Section>
              <Section label="Store tags" extra={<span className="muted small">(from your store's list, comma-separated)</span>} dirty={dirty("store_tags")} edited={copy.store_tags !== undefined && JSON.stringify(copy.store_tags) !== JSON.stringify(dr.proposed.store_tags)} locked={locked} busy={busy === "store_tags"} checks={checks["store_tags"]}
                onSave={() => saveField("store_tags", local!["store_tags"])} onDiscard={() => discard("store_tags")} onRevert={() => saveField("store_tags", null)}>
                <input value={local.store_tags} onChange={(e) => setField("store_tags", e.target.value)} />
                {dr.proposed_new_tags.length > 0 && <p className="muted small">Suggested new store tags (add them to the store first): {dr.proposed_new_tags.join(", ")}</p>}
              </Section>
              <Section label="Search keywords" extra={<span className="muted small">(comma-separated)</span>} dirty={dirty("search_keywords")} edited={copy.search_keywords !== undefined && JSON.stringify(copy.search_keywords) !== JSON.stringify(dr.proposed.search_keywords)} locked={locked} busy={busy === "search_keywords"} checks={checks["search_keywords"]}
                onSave={() => saveField("search_keywords", local!["search_keywords"])} onDiscard={() => discard("search_keywords")} onRevert={() => saveField("search_keywords", null)}>
                <input value={local.search_keywords} onChange={(e) => setField("search_keywords", e.target.value)} />
              </Section>
              </>)}

              <button className="link" onClick={() => setShowDraft(!showDraft)}>{showDraft ? "Hide" : "Show"} what the draft said</button>
              {showDraft && (
                <div className="draft-said">
                  <p><strong>{dr.proposed.title}</strong></p><p>{dr.proposed.short_description}</p><p>{dr.proposed.collector_description}</p>
                </div>
              )}

              <MeaningPanel d={d} questions={dr.ask_artist} onSaved={async () => { await load(); onChange(); }} />
              <div id="store"><StorefrontPanel id={d.item.id} version={JSON.stringify([d.listing, dr.revision, storeRev])} onChange={() => { refreshStatus(); onChange(); }} /></div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

const toStore = (e: React.MouseEvent) => { e.preventDefault(); document.getElementById("store")?.scrollIntoView({ behavior: "smooth", block: "start" }); };

// The one thing to do next, at the top of the page (B-074). Price and "sold as" can be answered right here; they
// save the same way as About this piece.
// The store steps a status can be at (B-088): the next-step bar does them itself, so every action is at the top.
const STORE_STEPS = ["approve-for-store", "ready-to-publish", "changed", "ready-to-update", "needs-look"];

// The details a piece needs for the store (B-090): About this piece, just above the bar, asks for them.
const DETAIL_TARGETS = ["product.price", "product.sold_as", "product.material", "product.dimensions"];

function NextStep({ d, approve, onStore }: {
  d: Detail; approve: (() => void) | null; onStore: () => Promise<void>;
}) {
  const st = d.status;
  const details = st.blockers.filter((b) => DETAIL_TARGETS.includes(b.target));
  const others = st.blockers.filter((b) => !DETAIL_TARGETS.includes(b.target));
  return (
    <section className={`next-step tone-${st.tone}`} aria-label="Next step">
      <div className="next-text">
        <h2>{st.next}</h2>
        {details.length > 0 && <p className="small muted">Fill in {details.length === 1 ? "the missing detail" : `the ${details.length} missing details`} in About this piece, above.</p>}
        {others.length > 0 && <ul className="small">{others.map((b) => <li key={b.target}>{b.question}</li>)}</ul>}
      </div>
      {approve && <button onClick={approve}>Approve copy</button>}
      {!approve && others.length > 0 && <a className="button-link secondary-link" href="#store" onClick={toStore}>See the details</a>}
      {STORE_STEPS.includes(st.id) && <StoreStep id={d.item.id} status={st.id} onDone={onStore} />}
    </section>
  );
}

// Approve for the store, then publish (or approve and send an update), from the top of the page. It reads the same
// preview as the store panel lower down and acts on the version shown there, by its hash, as that panel does.
function StoreStep({ id, status, onDone }: { id: string; status: string; onDone: () => Promise<void> }) {
  const [p, setP] = useState<StorefrontPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { api.storefront(id).then(setP).catch((e) => setMsg(String(e.message))); }, [id, status]);
  if (!p?.available || !p.change_set) return msg ? <p className="error small">{msg}</p> : null;
  const cs = p.change_set, a = p.approval!, pub = p.publish!, up = !!p.update;
  const name = p.display_name || "the store";
  async function act(fn: () => Promise<StorefrontPreview>) {
    setBusy(true); setMsg(null);
    try { setP(await fn()); await onDone(); }
    catch (e) { setMsg(String((e as Error).message)); setP(await api.storefront(id)); }
    setBusy(false);
  }
  const working = pub.state === "QUEUED" || pub.state === "WRITING";
  const canSend = a.state === "current" && !working && pub.state !== "OUTCOME_UNKNOWN"
    && (pub.state === null || pub.state === "FAILED" || (up && pub.state === "SUCCEEDED"));
  return (
    <div className="next-store">
      {a.state !== "current" && (
        <>
          <button disabled={busy || !p.approvable} onClick={() => act(() => api.approveStorefront(id, cs.change_set_hash, cs.requested_status))}>
            {busy ? "Approving…" : up ? "Approve update" : `Approve for ${name} as Draft`}</button>
          <a className="small" href="#store" onClick={toStore}>See what it sends</a>
        </>)}
      {canSend && (
        <button disabled={busy || pub.kill_switch.on} onClick={() => act(() => api.publish(id, cs.change_set_hash))}>
          {busy ? "Sending…" : up ? (pub.state === "FAILED" ? "Send the update again" : "Update in store")
            : `${pub.state === "FAILED" ? "Publish again" : "Publish"} to ${pub.target.toLowerCase()}`}</button>)}
      {working && <span className="small">{pub.state === "QUEUED" ? "Queued for the publisher…" : "Publishing…"}</span>}
      {pub.state === "OUTCOME_UNKNOWN" && <a className="button-link" href="#store" onClick={toStore}>Check the store</a>}
      {canSend && pub.kill_switch.on && <span className="small warn-text">Writing is switched off.</span>}
      {msg && <span className="error small">{msg}</span>}
    </div>
  );
}

function Section({ label, extra, dirty, edited, locked, busy, checks, onSave, onDiscard, onRevert, children }: {
  label: string; extra?: ReactNode; dirty: boolean; edited: boolean; locked: boolean; busy: boolean; checks?: Check[];
  onSave: () => void; onDiscard: () => void; onRevert: () => void; children: ReactNode;
}) {
  return (
    <fieldset disabled={locked} className={dirty ? "dirty" : ""}>
      <legend>{label} {extra}
        {dirty ? <span className="badge warn">Not saved</span> : edited && !locked ? <span className="badge">Your edit</span> : null}</legend>
      {children}
      {!locked && (dirty || edited) && (
        <div className="row section-actions">
          {dirty && <button disabled={busy} onClick={onSave}>{busy ? "Saving…" : label === "Title" ? "Save title" : "Save changes"}</button>}
          {dirty && <button className="secondary" disabled={busy} onClick={onDiscard}>Discard</button>}
          {!dirty && edited && <button className="link" disabled={busy} onClick={onRevert}>Back to the draft</button>}
        </div>
      )}
      {!dirty && checks && checks.length > 0 && (
        <ul className="section-checks">{checks.map((c, i) => <li key={i} className={`sev-${c.severity}`}>{c.message}</li>)}</ul>
      )}
      {!dirty && checks && checks.length === 0 && <p className="muted small">Saved. Nothing to flag.</p>}
    </fieldset>
  );
}

function Count({ n, range, chars, max }: { n: number; range: number[]; chars?: number; max?: number }) {
  const ok = n >= range[0] && n <= range[1] && (chars === undefined || max === undefined || chars <= max);
  return <span className={`count ${ok ? "" : "off"}`}>{n} words{chars !== undefined ? ` · ${chars} chars` : ""} (target {range[0]}–{range[1]})</span>;
}

// a blocking item the owner has since answered under "About this piece"
// Copied from packages/drafting/listing.py (SUPPLIED_BY): change both.
const SUPPLIED_BY: Record<string, "medium" | "dimensions"> = { "product.material": "medium", "product.dimensions": "dimensions" };

function ReviewTabs({ dr, facts }: { dr: Draft; facts: { medium?: string; dimensions?: string } }) {
  const [tab, setTab] = useState<"checks" | "evidence">("checks");
  const supplied = (i: Issue) => i.severity === "blocking" && !!facts[SUPPLIED_BY[i.target]];
  const done = dr.issues.filter(supplied);
  const by = (s: Issue["severity"]) => dr.issues.filter((i) => i.severity === s && !supplied(i));
  const tabs = [
    { id: "checks" as const, label: `Checks${by("blocking").length ? ` · ${by("blocking").length} to fix` : ""}` },
    { id: "evidence" as const, label: "Visible, confirmed and proposed" },
  ];
  return (
    <section className="panel tabbed">
      <div className="tabs" role="tablist" aria-label="Review">
        {tabs.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
            className={`tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      {tab === "checks" && (
        <div role="tabpanel" id="panel-checks" aria-labelledby="tab-checks">
          {(["blocking", "warning", "note"] as const).map((s) => by(s).length > 0 && (
            <div key={s}><h3 className={`sev-${s}`}>{s === "blocking" ? "To supply or fix" : s === "warning" ? "Worth a look" : "Notes"}</h3>
              <ul>{by(s).map((i) => <li key={i.id}>{i.question}</li>)}</ul></div>
          ))}
          {done.length > 0 && (
            <div><h3 className="sev-ok">Supplied since this draft</h3>
              <ul>{done.map((i) => <li key={i.id} className="muted">{SUPPLIED_BY[i.target] === "medium" ? "Medium" : "Size"}: {facts[SUPPLIED_BY[i.target]]}. Redraft to use it in the copy.</li>)}</ul></div>
          )}
          {dr.issues.length === 0 && <p className="muted small">Nothing to flag.</p>}
          <h3>Self-review</h3>
          <ul className="scores">
            {Object.entries(dr.self_review).map(([k, v]) => <li key={k}>{RUBRIC_LABELS[k] || k}: <strong>{v}</strong>/2</li>)}
          </ul>
          <p className="muted small">These are from the last draft. Edits you save are checked in their own section.</p>
        </div>
      )}
      {tab === "evidence" && (
        <div role="tabpanel" id="panel-evidence" aria-labelledby="tab-evidence">
          <ul className="evidence">
            {dr.observations.map((o) => <li key={o}><span className="badge">Visible</span> {o}</li>)}
            {dr.interpretations.map((i) => (
              <li key={i.statement}><span className={`badge ${i.basis === "confirmed" ? "ok" : "warn"}`}>{i.basis === "confirmed" ? `Confirmed ${i.meaning_id}` : "Proposed"}</span> {i.statement}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function MeaningPanel({ d, questions, onSaved }: { d: Detail; questions: string[]; onSaved: () => Promise<void> }) {
  const l = d.listing;
  const series = l.series || "";
  const [note, setNote] = useState(l.note || "");
  const [scope, setScope] = useState<"artwork" | "series" | "catalog">("artwork");
  const [subject, setSubject] = useState("");
  const [meaning, setMeaning] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const noteDirty = note !== (l.note || "");

  async function saveNote() {
    setMsg(null);
    try { await api.saveListing(d.item.id, { note }); setMsg("Saved. Redraft to use it."); await onSaved(); }
    catch (e) { setMsg(String((e as Error).message)); }
  }
  async function record() {
    setMsg(null);
    try {
      await api.addMeaning(d.item.id, { scope, subject, meaning, series });
      setSubject(""); setMeaning(""); setMsg("Recorded as a confirmed meaning. Redraft to use it."); await onSaved();
    } catch (e) { setMsg(String((e as Error).message)); }
  }
  return (
    <section className="panel meaning">
      <h2>What this piece means</h2>
      {questions.length > 0 && (
        <div className="questions">
          <h3>Questions for the artist</h3>
          <ul>{questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}
      <label>Note for the writer <span className="muted small">(your words; it outranks the model's reading)</span>
        <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. The wolf is the part of me that keeps going alone." /></label>
      {noteDirty && (
        <div className="row section-actions">
          <button onClick={saveNote}>Save note</button>
          <button className="secondary" onClick={() => setNote(l.note || "")}>Discard</button>
        </div>
      )}

      <details>
        <summary>Record a confirmed meaning</summary>
        <div role="radiogroup" aria-label="Applies to" className="row">
          {(["artwork", "series", "catalog"] as const).map((s) => (
            <label key={s} className="inline"><input type="radio" checked={scope === s} disabled={s === "series" && !series} onChange={() => setScope(s)} />
              {s === "artwork" ? "This piece" : s === "series" ? (series ? `This series (${series})` : "This series (set one under About this piece)") : "Whole catalog"}</label>
          ))}
        </div>
        <label>About <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. the wolf" /></label>
        <label>Means <textarea rows={2} value={meaning} onChange={(e) => setMeaning(e.target.value)} placeholder="e.g. self-reliance when the path is lonely" /></label>
        <button className="secondary" disabled={!subject || !meaning} onClick={record}>Record meaning</button>
      </details>
      {msg && <p className="muted small">{msg}</p>}
      {d.meanings.length > 0 && (
        <>
          <h3>Meanings that apply here</h3>
          <ul className="small">{d.meanings.map((m) => <li key={m.id}><span className="badge">{m.scope.kind}{m.scope.ref ? `: ${m.scope.ref}` : ""}</span> {m.subject}: {m.meaning}</li>)}</ul>
        </>
      )}
    </section>
  );
}
