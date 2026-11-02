import { useCallback, useEffect, useRef, useState } from "react";
import { api, Job, PhotoDetail, Pt, waitForJob } from "../api";
import { CornerEditor, same } from "../components/CornerEditor";
import { Drawer } from "../components/Drawer";
import { AboutPiece } from "../components/AboutPiece";
import { ago } from "./Photos";

// One photo: the original with the outline the crop found, corners you can drag, and what came out (B-062),
// and the piece on the wall of its room, which you can change (B-063).

export function PhotoDetailPage({ id, onChange }: { id: string; onChange: () => void }) {
  const [p, setP] = useState<PhotoDetail | null>(null);
  const [pts, setPts] = useState<Pt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [hanging, setHanging] = useState(false);
  const [changing, setChanging] = useState(false);
  const [pick, setPick] = useState<string | null>(null);     // in the drawer: a room id, or "auto"
  const tried = useRef<string | null>(null);
  const changeBtn = useRef<HTMLButtonElement | null>(null);
  const [moved, setMoved] = useState<string | null>(null);   // the automatic room changed after a size change

  const load = useCallback(() => api.photo(id).then((d) => {
    setP(d); setPts((d.corners || d.detected.corners || null)?.map((q) => [...q] as Pt) || null);
  }).catch((e) => setError(String(e.message || e))), [id]);
  useEffect(() => { load(); }, [load]);

  const saved = p ? (p.corners || p.detected.corners) : null;
  const dirty = !!pts && !same(pts, saved);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {                                          // show it on the wall: make the view when it's missing or old
    const v = p?.room;
    if (!p || !v || !v.stale || p.stage === "not-applied" || hanging) return;
    const key = `${p.id}:${v.room}:${p.dimensions || ""}`;     // again when the room or the size changes
    if (tried.current === key) return;                       // once per piece and room, not in a loop
    tried.current = key;
    setHanging(true);
    api.photoRoom(p.id).then(setP).catch((e) => setError(String(e.message || e))).finally(() => setHanging(false));
  }, [p, hanging]);

  if (!p) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const [W, H] = p.photo_size || [1, 1];
  const isPhoto = p.kind === "photo" && !!p.photo && !!p.photo_size;
  async function send(body: Parameters<typeof api.decidePhoto>[1]) {
    setBusy(true); setError(null);
    try { await api.decidePhoto(p!.id, body); await load(); onChange(); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }
  async function apply() {
    setError(null);
    try {
      const { job: jid } = await api.applyPhotos();
      const j = await waitForJob(jid, setJob);
      if (j.error) setError(j.error);
      await load(); onChange();
    } catch (e) { setError(String((e as Error).message)); }
  }
  const leave = (e: React.MouseEvent) => { if (dirty && !confirm("Your corner changes aren't saved. Leave anyway?")) e.preventDefault(); };
  const label = { "to-review": "To review", "not-applied": "Not applied", ready: "Ready to draft", drafted: "Drafted",
                  approved: "Copy approved", rejected: "Rejected" }[p.stage];
  async function hang(body: { room?: string | null } = {}) {
    setHanging(true); setError(null);
    try { setP(await api.photoRoom(p!.id, body)); setChanging(false); }
    catch (e) { setError(String((e as Error).message)); }
    setHanging(false);
  }
  const view = p.room;
  const current = view ? (view.auto ? "auto" : view.room) : "auto";

  return (
    <main className="page photo-page">
      <div className="row between">
        <div className="row">
          <a href="#/photos" onClick={leave}>← Photos</a>
          <h1 className="photo-title">{p.source}</h1>
          <span className={`badge ${p.stage === "approved" ? "ok" : p.stage === "rejected" ? "bad" : p.stage === "ready" || p.stage === "drafted" ? "" : "warn"}`}>{label}</span>
        </div>
        <div className="row">
          {p.prev && <a href={`#/photos/${p.prev}`} onClick={leave}>← Previous</a>}
          {p.next && <a href={`#/photos/${p.next}`} onClick={leave}>Next →</a>}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="photo-layout">
        <section aria-labelledby="corners-h">
          {isPhoto ? (<>
            <h2 id="corners-h">Corners</h2>
            <p className="muted small">
              {p.corners ? "Your corrected corners." : p.detected.ok ? `The outline the crop found (${p.detected.method}).`
                : `The crop wasn't sure${p.detected.reasons[0] ? `: ${p.detected.reasons[0]}` : ""}. Drag the corners onto the artwork's edges.`}
              {" "}Drag a corner, or click to bring the nearest one there. Tab to a corner and use the arrow keys to nudge it (Shift for bigger steps).
            </p>
            <CornerEditor src={`/${p.photo}`} alt={`Original photo ${p.source}`} size={[W, H]} pts={pts}
                          onChange={setPts} ghost={p.corners ? p.detected.corners : null} label="Crop corners" />
            <div className="row section-actions">
              <button disabled={!dirty || busy} onClick={() => send({ corners: pts })}>Save corners</button>
              <button className="secondary" disabled={!dirty || busy} onClick={() => setPts(saved ? saved.map((q) => [...q] as Pt) : null)}>Discard</button>
              {p.corners && <button className="link" disabled={busy} onClick={() => send({ corners: null })}>Back to the outline the crop found</button>}
              <button className="link" disabled={busy} onClick={() => setPts([[0, 0], [W, 0], [W, H], [0, H]])}>Whole photo</button>
              {dirty && <span className="badge warn">Not saved</span>}
            </div>
          </>) : (<>
            <h2 id="corners-h">Original</h2>
            <p className="muted small">A ready-cut file: there's nothing to crop, so it's framed as it is.</p>
            {(p.original || p.image) && <img className="photo-original" src={`/${p.original || p.image}`} alt={`Original file ${p.source}`} />}
          </>)}
        </section>

        <aside className="photo-side">
          {p.stage === "not-applied" && (
            <div className="panel dirty">
              <strong>Saved, not applied yet.</strong>
              <p className="small muted">The crop and frame below still show the old {p.rotate !== p.applied.rotate ? "rotation" : "corners"}.</p>
              <button disabled={!!job?.running} onClick={apply}>{job?.running ? `Applying ${job.done}/${job.total}…` : "Apply changes"}</button>
            </div>
          )}
          <div className="row results">
            {p.cropped && <figure><img src={`/${p.cropped}`} alt="The cropped artwork" /><figcaption className="small muted">Cropped</figcaption></figure>}
            {p.framed && <figure><img src={`/${p.framed}`} alt="The framed preview" /><figcaption className="small muted">Framed</figcaption></figure>}
          </div>
          <div className="row photo-actions">
            <button className={p.decision === "accept" ? "" : "secondary"} disabled={busy} aria-pressed={p.decision === "accept"}
              onClick={() => send({ decision: p.decision === "accept" ? null : "accept" })}>{p.decision === "accept" ? "✓ Accepted" : "Accept"}</button>
            <button className="secondary" disabled={busy} onClick={() => send({ rotate: (p.rotate + 90) % 360 })}>
              Rotate ↻{p.rotate ? ` ${p.rotate}°` : ""}</button>
            <button className={p.decision === "reject" ? "danger" : "secondary danger"} disabled={busy} aria-pressed={p.decision === "reject"}
              onClick={() => send({ decision: p.decision === "reject" ? null : "reject" })}>{p.decision === "reject" ? "✗ Rejected" : "Reject"}</button>
          </div>
          <h2>History</h2>
          <ol className="timeline">
            {p.events.map((e, n) => (
              <li key={n} title={e.at ? new Date(e.at).toLocaleString() : undefined}>{e.label} <span className="muted">{ago(e.at)}</span></li>
            ))}
          </ol>
          <label className="small">Note
            <textarea rows={2} defaultValue={p.note} onBlur={(e) => e.target.value !== p.note && send({ note: e.target.value })} />
          </label>
          <AboutPiece key={p.id} itemId={p.id} series={p.series} facts={p.facts} sizeFromName={p.size_from_name}
                      note={p.stage === "approved" ? "The copy is approved: unlock and redraft it to use this."
                        : p.stage === "drafted" ? "Redraft the copy to use it." : undefined}
                      onSaved={async () => {
                        const before = p.room;
                        const d = await api.photo(p.id);
                        setP(d); onChange();
                        setMoved(before && d.room && before.auto && d.room.auto && before.room !== d.room.room
                          ? `Moved to ${d.room.name} from ${before.name}: at this size it suits that wall better.` : null);
                      }} />
          <h2>In a room</h2>
          {moved && <p className="small banner-inline" role="status">{moved}</p>}
          {!p.framed ? <p className="small muted">Once the piece is cropped and framed, it's hung in a room.</p>
            : !view ? (<>
              <div className="room-empty small muted">No room is ready yet</div>
              <div className="row between section-actions">
                <span className="small muted">A room needs its licence and its wall. <a href="#/rooms" onClick={leave}>Rooms page →</a></span>
                <button ref={changeBtn} className="secondary" aria-haspopup="dialog" aria-expanded={changing}
                        onClick={() => { setPick(current); setChanging(true); }}>Change room</button>
              </div>
            </>)
            : (<>
              <figure className="room-view">
                {view.image ? <a href={`/${view.image}`} target="_blank" rel="noreferrer"><img src={`/${view.image}`} alt={`${p.source} on the wall in ${view.name}`} /></a>
                  : <div className="room-empty small muted">{hanging ? "Hanging it…" : "Not made yet"}</div>}
                <figcaption className="row between small">
                  <span>{view.name} <span className="muted">{view.auto ? "(picked automatically)" : "(your choice)"}</span>
                    {view.image && view.stale && !hanging && <span className="badge warn">Out of date</span>}</span>
                  <button ref={changeBtn} className="secondary" disabled={hanging} aria-haspopup="dialog" aria-expanded={changing}
                          onClick={() => { setPick(current); setChanging(true); }}>Change room</button>
                </figcaption>
              </figure>
              {view.unavailable && <p className="small warn-text">{view.unavailable} can't be used any more, so a room was picked for it.</p>}
              <p className="small muted">
                {view.guessed
                  ? <>Size guessed: {p.dimensions ? `"${p.dimensions}" has no unit` : "no size is given yet"}. Give its size above, under About this piece, to hang it at its real size.</>
                  : <>Hung at its real size ({p.dimensions}).</>}
                {view.fitted && " Shrunk to fit the wall."}
                {view.overflows && ` Bigger than the wall area marked in ${view.name}, so it may overlap the furniture there. ${view.fits_elsewhere.length
                  ? `It fits in ${view.fits_elsewhere.join(", ")}: try Change room.` : "No room's wall is big enough for it at this size."}`}
              </p>
              {p.stage === "not-applied" && <p className="small muted">Apply your changes first to see them on the wall.</p>}
              {view.image && view.stale && !hanging && p.stage !== "not-applied" &&
                <button className="secondary" onClick={() => hang()}>Make it again</button>}
            </>)}
          {changing && (
            <Drawer title="Change room" onClose={() => setChanging(false)} busy={hanging} opener={changeBtn} focus="input[type=radio]:checked" className="room-picker">
              <fieldset className="room-options">
                <legend className="small muted">Pick the room {p.listing_title ? `"${p.listing_title}"` : "this piece"} is shown in.</legend>
                <label className={`room-option ${pick === "auto" ? "on" : ""}`}>
                  <input type="radio" name="room" value="auto" checked={pick === "auto"} onChange={() => setPick("auto")} />
                  <span className="room-auto" aria-hidden="true">✦</span>
                  <span><strong>Pick for me</strong><span className="small muted">The ready room whose wall best suits its shape and size.</span></span>
                </label>
                {p.room_options.map((o) => {
                  const ok = o.status === "ready";
                  return (
                    <label key={o.id} className={`room-option ${pick === o.id ? "on" : ""} ${ok ? "" : "off"}`}>
                      <input type="radio" name="room" value={o.id} disabled={!ok} checked={pick === o.id} onChange={() => setPick(o.id)} />
                      <img src={`/${o.preview || o.image}`} alt="" loading="lazy" />
                      <span><strong>{o.name}</strong>{o.id === view?.room && <span className="badge">Now</span>}
                        {!ok && <span className="small muted">{{ "needs-licence": "Needs a licence", "needs-wall": "Wall not marked yet", off: "Turned off", ready: "" }[o.status]}
                          {" · "}<a href={`#/rooms/${o.id}`} onClick={leave}>set it up</a></span>}</span>
                    </label>
                  );
                })}
              </fieldset>
              <div className="row section-actions drawer-foot">
                <button disabled={hanging || pick === null || pick === current} onClick={() => hang({ room: pick === "auto" ? null : pick })}>
                  {hanging ? "Hanging…" : "Apply"}</button>
                <button className="secondary" disabled={hanging} onClick={() => setChanging(false)}>Cancel</button>
              </div>
              {error && <p className="error">{error}</p>}
            </Drawer>
          )}
          {(p.stage === "drafted" || p.stage === "approved") &&
            <p><a href={`#/listings/${p.id}`} onClick={leave}>Listing: {p.listing_title || "open"} →</a></p>}
        </aside>
      </div>
    </main>
  );
}
