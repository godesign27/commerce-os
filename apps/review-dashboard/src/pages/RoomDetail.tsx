import { useCallback, useEffect, useState } from "react";
import { api, Pt, Room, RoomChanges, roomLabel, RoomsDoc } from "../api";
import { CornerEditor, same } from "../components/CornerEditor";

// Setting up one room (B-063). A room is used once three things are done: its licence is recorded, the area
// of wall a piece can hang on is marked, and that area's real width is given. A new room arrives with a
// suggested area and width (room_suggest.py); they're pre-filled here and only count once you save them.
type Unit = "in" | "cm";

function starter([W, H]: [number, number]): Pt[] {           // no suggestion: a band across the upper middle
  return [[W * 0.3, H * 0.18], [W * 0.7, H * 0.18], [W * 0.7, H * 0.5], [W * 0.3, H * 0.5]];
}
const asUnit = (cm: number, u: Unit) => String(+(u === "in" ? cm / 2.54 : cm).toFixed(1));
const across = (w: Pt[]) => (Math.hypot(w[1][0] - w[0][0], w[1][1] - w[0][1]) + Math.hypot(w[2][0] - w[3][0], w[2][1] - w[3][1])) / 2;

// A width for a box you drew yourself, from the suggestion's scale (cm per pixel across the wall). Close enough
// for a photo taken square-on; it's pre-filled for you to check, never saved on its own.
function scaledWidth(r: Room): number | null {
  const s = r.suggested;
  if (!r.wall || r.wall_width_cm || !s?.wall || !s.wall_width_cm) return null;
  return Math.round(across(r.wall) * s.wall_width_cm / across(s.wall));
}

export function RoomDetail({ id }: { id: string }) {
  const [room, setRoom] = useState<Room | null>(null);
  const [doc, setDoc] = useState<RoomsDoc | null>(null);
  const [form, setForm] = useState<RoomChanges>({});
  const [pts, setPts] = useState<Pt[] | null>(null);
  const [unit, setUnit] = useState<Unit>("in");
  const [width, setWidth] = useState("");
  const [piece, setPiece] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback((r: Room, u: Unit) => {
    setRoom(r); setForm({});
    const sug = !r.wall && r.suggested?.wall ? r.suggested : null;    // a suggestion fills in what isn't set yet
    setPts((r.wall || sug?.wall || starter(r.size)).map((q) => [...q] as Pt));
    const cm = r.wall_width_cm ?? (sug ? sug.wall_width_cm : scaledWidth(r));
    setWidth(cm ? asUnit(cm, u) : "");
  }, []);
  useEffect(() => {
    Promise.all([api.room(id), api.rooms()]).then(([r, d]) => { reset(r, unit); setDoc(d); })
      .catch((e) => setError(String(e.message || e)));
  }, [id]);                                                   // eslint-disable-line react-hooks/exhaustive-deps

  const widthCm = width.trim() === "" ? null : Math.round(parseFloat(width) * (unit === "in" ? 2.54 : 1) * 10) / 10;
  const changes: RoomChanges = { ...form };
  if (room) {
    if (pts && !same(pts, room.wall)) changes.wall = pts;
    if (widthCm !== room.wall_width_cm && !(widthCm !== null && room.wall_width_cm !== null && Math.abs(widthCm - room.wall_width_cm) < 0.2))
      changes.wall_width_cm = widthCm;
  }
  const dirty = Object.keys(changes).length > 0;
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!room || !doc) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const val = <K extends keyof RoomChanges>(k: K) => (k in form ? form[k] : room[k as keyof Room]) as Room[K & keyof Room];
  const set = (k: keyof RoomChanges, v: unknown) => setForm((f) => {
    const next = { ...f, [k]: v } as RoomChanges;
    if (JSON.stringify(v) === JSON.stringify(room[k as keyof Room])) delete next[k];
    return next;
  });

  async function save() {
    setBusy("save"); setError(null);
    try { reset(await api.saveRoom(room!.id, changes), unit); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(null);
  }
  async function preview() {
    setBusy("preview"); setError(null);
    try { const r = await api.previewRoom(room!.id, piece || undefined); setRoom(r); setPiece(r.preview_piece || piece); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(null);
  }
  function useSuggested() {
    if (!room?.suggested?.wall) return;
    setPts(room.suggested.wall.map((q) => [...q] as Pt));
    if (room.suggested.wall_width_cm) setWidth(asUnit(room.suggested.wall_width_cm, unit));
  }
  async function suggestAgain() {
    if (dirty && !confirm("Asking again replaces your unsaved corners and width with the new suggestion. Go on?")) return;
    setBusy("suggest"); setError(null);
    try {
      const r = await api.suggestRoom(room!.id);
      reset(r, unit);
      if (r.suggested?.wall) {                                // show the new suggestion even when a wall is saved
        setPts(r.suggested.wall.map((q) => [...q] as Pt));
        if (r.suggested.wall_width_cm) setWidth(asUnit(r.suggested.wall_width_cm, unit));
      }
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(null);
  }
  const leave = (e: React.MouseEvent) => { if (dirty && !confirm("Your changes to this room aren't saved. Leave anyway?")) e.preventDefault(); };
  const status = roomLabel(room, doc.statuses);
  const licence = val("licence");
  const sug = room.suggested;
  const showingSuggestion = !!sug?.wall && !!pts && same(pts, sug.wall) && !same(pts, room.wall);
  const licenceOk = !!licence && !(licence === "other" && !(val("note") as string).trim());
  const isStarter = !!pts && same(pts, starter(room.size));       // the untouched box every room starts with
  const areaMoved = !!pts && !same(pts, room.wall);
  const widthMoved = "wall_width_cm" in changes;
  const todo = [!licenceOk && "the licence", !pts && "where pieces hang", !widthCm && "the width"].filter(Boolean) as string[];
  const ready = room.status === "ready" && !dirty;
  const [W, H] = room.size;

  return (
    <main className="page photo-page">
      <div className="row">
        <a href="#/rooms" onClick={leave}>← Rooms</a>
        <h1 className="photo-title">{room.name}</h1>
        <span className={`badge ${room.status === "ready" ? "ok" : room.status === "off" ? "" : "warn"}`}>{status}</span>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="photo-layout">
        <section aria-labelledby="wall-h">
          <h2 id="wall-h">Where pieces hang</h2>
          {showingSuggestion ? (
            <p className="banner-inline small">
              <strong>Suggested from the photo.</strong> The box and the width{sug!.reference ? ` (judged from ${sug!.reference})` : ""} are
              a {sug!.confidence === "high" ? "confident" : sug!.confidence === "medium" ? "fair" : "rough"} guess: check them, then press <strong>Save room</strong>.
            </p>
          ) : room.wall && sug?.wall && !same(sug.wall, room.wall) && pts && !same(pts, sug.wall) ? (
            <p className="banner-inline small">
              {!room.wall_width_cm && scaledWidth(room) ? <>The width is worked out for your box from the suggestion's scale: check it, then press <strong>Save room</strong>. </> : null}
              There's also a suggested area for this room. <button className="link" onClick={useSuggested}>Use the suggested area</button>
            </p>
          ) : !room.wall ? (
            <p className="banner-inline small">The box is only a starting point: drag it onto the empty wall, then press <strong>Save room</strong>.</p>
          ) : null}
          <p className="muted small">
            Put the four corners on the part of the wall a piece can hang on (above the sofa, say), following the wall's
            angle. Pieces are centred in it. Drag a corner, or click to bring the nearest one there; Tab to a corner and
            use the arrow keys to nudge it (Shift for bigger steps).
          </p>
          <div className="room-stage" style={{ maxWidth: `min(100%, calc(70vh * ${W / H}))` }}>
            <CornerEditor src={`/${room.image}`} alt={`Room photo ${room.name}`} size={room.size} pts={pts}
                          onChange={setPts} ghost={room.wall && pts && !same(pts, room.wall) ? room.wall : null} label="Hanging area corners" />
          </div>
        </section>

        <aside className="photo-side">
          <section className={`panel setup ${ready ? "is-ready" : "dirty"}`} aria-labelledby="setup-h">
            <h2 id="setup-h">{ready ? "✓ Ready to use" : "Set up this room"}</h2>
            <p className="small muted">{ready
              ? "Pieces can hang in this room. Preview it below, or pick it with Change room on any photo's page."
              : "Three steps, then Save. The room is only used once all three are saved."}</p>
            <ol className="steps">
              <li className={licenceOk ? (room.licence === licence ? "done" : "pending") : ""}>
                <span className="step-n" aria-hidden="true">{licenceOk && room.licence === licence ? "✓" : "1"}</span>
                <div>
                  <strong>Licence</strong>
                  <select value={licence || ""} onChange={(e) => set("licence", e.target.value || null)} aria-label="Licence">
                    <option value="">Not recorded: this room won't be used</option>
                    {doc.licences.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                  </select>
                  {licence === "other" && !(val("note") as string).trim() && <p className="small warn-text">Say which licence in the note, under Where it came from.</p>}
                </div>
              </li>
              <li className={pts && !isStarter ? (areaMoved ? "pending" : "done") : ""}>
                <span className="step-n" aria-hidden="true">{pts && !isStarter && !areaMoved ? "✓" : "2"}</span>
                <div>
                  <strong>Where pieces hang</strong>
                  <p className="small muted">{isStarter
                    ? "This is the starting box, not your wall yet. Drag its four corners, on the photo, onto the empty wall a piece would hang on."
                    : areaMoved ? (showingSuggestion ? "The suggested area is on the photo. Check it, then save." : "You've moved the corners. Save to keep them.")
                    : "Saved. Drag a corner on the photo to change it."}</p>
                  {sug?.wall && pts && !same(pts, sug.wall) && <button className="link small" onClick={useSuggested}>Use the suggested area</button>}
                </div>
              </li>
              <li className={widthCm ? (widthMoved ? "pending" : "done") : ""}>
                <span className="step-n" aria-hidden="true">{widthCm && !widthMoved ? "✓" : "3"}</span>
                <div>
                  <strong>How wide that area is in real life</strong>
                  <span className="row width-row">
                    <input type="number" min={1} step="any" value={width} placeholder="Width" onChange={(e) => setWidth(e.target.value)} aria-label="Width of the hanging area" />
                    <select value={unit} aria-label="Unit" onChange={(e) => {
                      const u = e.target.value as Unit;
                      if (width.trim()) setWidth(String(+(u === "cm" ? parseFloat(width) * 2.54 : parseFloat(width) / 2.54).toFixed(1)));
                      setUnit(u);
                    }}><option value="in">inches</option><option value="cm">cm</option></select>
                  </span>
                  <p className="small muted">{widthCm && !room.wall_width_cm && sug?.wall_width_cm
                    ? `Pre-filled from the photo${sug.reference ? `, judged from ${sug.reference}` : ""}: check it. `
                    : ""}Use what's in the photo: a sofa is about 80–90 in (200–230 cm) wide, a door about 32 in (80 cm). This sets how big each piece looks.</p>
                  {room.wall_height_cm && !dirty && <p className="small muted">Its height works out at about {unit === "in"
                    ? `${Math.round(room.wall_height_cm / 2.54)} in` : `${Math.round(room.wall_height_cm)} cm`}.</p>}
                </div>
              </li>
            </ol>
            {!ready && (
              <p className="small" role="status">{todo.length ? <>Still to do: {todo.join(", ")}.</>
                : dirty ? <>All three are filled in. <strong>Save</strong> to start using this room.</> : null}</p>
            )}
            <div className="row section-actions">
              <button disabled={!dirty || !!busy} onClick={save}>{busy === "save" ? "Saving…"
                : !todo.length && room.status !== "ready" ? "Save and use this room" : "Save room"}</button>
              {dirty && <button className="secondary" disabled={!!busy} onClick={() => reset(room, unit)}>Discard</button>}
              <button className="link" disabled={!!busy} onClick={suggestAgain}>{busy === "suggest" ? "Looking at the photo…" : sug ? "Suggest again" : "Suggest a wall and name"}</button>
            </div>
          </section>

          <h2>Preview</h2>
          {room.preview ? <a href={`/${room.preview}`} target="_blank" rel="noreferrer"><img className="room-preview" src={`/${room.preview}`} alt={`Preview of ${room.name} with a piece on the wall`} /></a>
            : <p className="small muted">Save the wall and its width, then preview it with a piece.</p>}
          <div className="row">
            <select value={piece} onChange={(e) => setPiece(e.target.value)} aria-label="Piece to preview with">
              <option value="">First piece</option>
              {doc.pieces.map((p) => <option key={p.id} value={p.id}>{p.source}</option>)}
            </select>
            <button className="secondary" disabled={!!busy || !room.wall || !room.wall_width_cm || dirty} onClick={preview}>
              {busy === "preview" ? "Hanging…" : "Preview"}</button>
          </div>
          {dirty && <p className="small muted">Save first to preview your changes.</p>}

          <h2>The room</h2>
          <label className="small">Name{room.named_by === "suggestion" && <span className="muted"> (suggested from the photo; change it if you like)</span>}
            <input value={val("name") as string} onChange={(e) => set("name", e.target.value)} /></label>
          <label className="small">Light <span className="muted">(how bright the piece looks in this room)</span>
            <input type="range" min={0.5} max={1.1} step={0.01} value={val("light") as number} onChange={(e) => set("light", +e.target.value)} /></label>
          <label className="small">Shadow
            <input type="range" min={0} max={0.8} step={0.01} value={val("shadow") as number} onChange={(e) => set("shadow", +e.target.value)} /></label>
          <label className="small inline"><input type="checkbox" checked={val("enabled") as boolean} onChange={(e) => set("enabled", e.target.checked)} />
            Use this room for listings</label>

          <h2>Where it came from</h2>
          <label className="small">Credit <span className="muted">(photographer or service)</span>
            <input value={val("credit") as string} onChange={(e) => set("credit", e.target.value)} /></label>
          <label className="small">Source link<input value={val("url") as string} placeholder="https://" onChange={(e) => set("url", e.target.value)} /></label>
          <label className="small">Note{licence === "other" && <span className="muted"> (say which licence)</span>}
            <textarea rows={2} value={val("note") as string} onChange={(e) => set("note", e.target.value)} /></label>
          <p className="small muted">File: {room.source_file}</p>
          <div className="row section-actions">
            <button disabled={!dirty || !!busy} onClick={save}>{busy === "save" ? "Saving…" : "Save room"}</button>
            {dirty && <span className="badge warn">Not saved</span>}
          </div>
        </aside>
      </div>
    </main>
  );
}
