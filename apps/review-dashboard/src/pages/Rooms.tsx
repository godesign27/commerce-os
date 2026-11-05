import { useCallback, useEffect, useRef, useState } from "react";
import { api, Job, roomLabel, RoomsDoc, RoomStatus, waitForJob } from "../api";
import { Drawer } from "../components/Drawer";

// The room library (B-063): room photos the owner has the right to use, each with its wall marked, for
// hanging every framed piece in a real-looking room.
const STATUS_CLASS: Record<RoomStatus, string> = { ready: "ok", "needs-licence": "warn", "needs-wall": "warn", off: "" };

export function Rooms() {
  const [doc, setDoc] = useState<RoomsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [adding, setAdding] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState({ name: "", licence: "", credit: "" });
  const picker = useRef<HTMLInputElement | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const close = () => { setAdding(false); setFiles([]); };
  const load = useCallback(() => api.rooms().then(setDoc).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { load(); }, [load]);

  async function scan() {
    setBusy(true); setError(null); setNote(null);
    try {
      const { added } = await api.scanRooms();
      await load();
      setNote(added.length ? `Added ${added.length} room${added.length > 1 ? "s" : ""}.` : "No new photos in the inbox folder.");
      if (added.length) await suggest(added);
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }
  // Each new room gets a suggested name, hanging area and width (one model call each). The name is used
  // straight away; the area and width wait on the room's page until you save them.
  async function suggest(ids: string[]): Promise<boolean> {
    try {
      const { job: jid } = await api.suggestRooms(ids);
      const j = await waitForJob(jid, setJob);
      const failed = j.results.filter((r) => r.error);
      setNote(`Named ${j.done - failed.length} of ${ids.length} new room${ids.length > 1 ? "s" : ""} and suggested where pieces hang`
        + ` ($${j.cost_usd.toFixed(3)}). Open each one to check its wall and width, then save it.`
        + (failed.length ? ` Couldn't suggest for ${failed.length}: ${failed[0].error}` : ""));
      await load();
      return !failed.length;
    } catch (e) {
      setNote(`Added. Couldn't suggest names and walls: ${(e as Error).message}. Set each room up on its page.`);
      return false;
    }
  }
  async function upload() {
    setBusy(true); setError(null); setNote(null);
    const added: string[] = []; const newIds: string[] = []; const failed: string[] = []; let firstId = "";
    for (const f of files) {
      try {
        const r = await api.uploadRoom(f, { ...meta, name: files.length === 1 ? meta.name : "" });
        if (r.added) { added.push(r.name); newIds.push(r.id); } else failed.push(`${f.name}: already in the library as ${r.name}`);
        firstId ||= r.id;
      } catch (e) { failed.push(`${f.name}: ${(e as Error).message}`); }
    }
    if (newIds.length) await suggest(newIds);
    setBusy(false);
    if (files.length === 1 && newIds.length === 1) { window.location.hash = `#/rooms/${firstId}`; return; }
    if (failed.length) setNote((n) => [n, ...failed].filter(Boolean).join(" "));
    setFiles([]); setAdding(false); if (picker.current) picker.current.value = "";
    await load();
  }
  async function renderAll() {
    setError(null);
    try {
      const { job: id } = await api.renderRooms();
      const j = await waitForJob(id, setJob);
      if (j.error) setError(j.error);
      const failed = j.results.filter((r) => r.error).length;
      setNote(`Done: ${j.done} piece${j.done === 1 ? "" : "s"}${failed ? `, ${failed} couldn't be hung` : ""}. Open a photo to see it in its room.`);
    } catch (e) { setError(String((e as Error).message)); }
  }

  if (!doc) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const ready = doc.rooms.filter((r) => r.status === "ready").length;
  return (
    <main className="page">
      <div className="row between page-head">
        <h1>Rooms</h1>
        <div className="row">
          {job?.running && <span className="muted">{job.label}: {job.done}/{job.total}…</span>}
          <button ref={opener} onClick={() => setAdding(true)} aria-haspopup="dialog" aria-expanded={adding}>Add a room</button>
          <button className="secondary" disabled={busy} onClick={scan}>{busy && !adding ? "Looking…" : "Look for new rooms"}</button>
          <button className="secondary" disabled={!ready || !!job?.running} onClick={renderAll}>
            {ready ? "Hang every piece in its room" : "No room is ready yet"}</button>
        </div>
      </div>
      <details className="help"><summary className="small">How rooms work</summary><p className="muted small">
        Room photos for showing each framed piece on a wall. Press <strong>Add a room</strong> to upload one, or put
        photos in <code>{doc.inbox}</code> and press <strong>Look for new rooms</strong>. Use only photos you have the right to use: your own, or ones whose
        licence allows it. A room is used once its licence is recorded and its wall is marked.
      </p></details>
      {adding && (
        <Drawer title="Add a room" onClose={close} busy={busy} opener={opener} focus="input[type=file]" className="add-room">
          <label className="small">Room photo{files.length > 1 ? "s" : ""} <span className="muted">(JPEG, PNG, WebP, HEIC or TIFF; several at once is fine)</span>
            <input ref={picker} type="file" multiple accept="image/*,.heic" onChange={(e) => setFiles(Array.from(e.target.files || []))} /></label>
          {files.length === 1 && <label className="small">Name <span className="muted">(optional)</span>
            <input value={meta.name} placeholder={files[0].name.replace(/\.[^.]+$/, "")} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></label>}
          <label className="small">Licence
            <select value={meta.licence} onChange={(e) => setMeta({ ...meta, licence: e.target.value })}>
              <option value="">Not recorded yet: the room won't be used until it is</option>
              {doc.licences.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select></label>
          <label className="small">Credit <span className="muted">(photographer or service)</span>
            <input value={meta.credit} onChange={(e) => setMeta({ ...meta, credit: e.target.value })} /></label>
          {meta.licence === "other" && <p className="small muted">Say which licence in the room's note after it's added.</p>}
          <div className="row section-actions">
            <button disabled={!files.length || busy} onClick={upload}>{busy ? "Adding…" : files.length > 1 ? `Add ${files.length} rooms` : "Add room"}</button>
            <button className="secondary" disabled={busy} onClick={close}>Cancel</button>
          </div>
          <p className="small muted">Use only photos you have the right to use. After adding one, you'll mark where pieces hang on its wall.</p>
          {error && <p className="error">{error}</p>}
        </Drawer>
      )}
      {error && <p className="error">{error}</p>}
      {note && <p className="banner-inline">{note}</p>}
      <ul className="grid room-grid">
        {[...doc.rooms].sort((a, b) => Number(!a.enabled) - Number(!b.enabled) || b.added_at.localeCompare(a.added_at))
          .map((r) => {                                       // newest first; turned-off rooms last
          const st: RoomStatus = r.enabled ? r.status : "off";
          const label = roomLabel(r, doc.statuses);
          return (
          <li key={r.id} className="card">
            <a className="photo-open" href={`#/rooms/${r.id}`} aria-label={`Set up ${r.name}`}>
              <img src={`/${r.preview || r.image}`} alt="" loading="lazy" />
            </a>
            <div className="card-body">
              <span className="row between">
                <a className="small photo-name" href={`#/rooms/${r.id}`}>{r.name}</a>
                <span className={`badge ${STATUS_CLASS[st]}`}>{label}</span>
              </span>
              <span className="small muted">
                {r.licence ? doc.licences.find((l) => l.id === r.licence)?.label.split(" (")[0] : "Licence not recorded"}
                {r.credit ? ` · ${r.credit}` : ""}
                {r.wall_width_cm ? ` · wall ${Math.round(r.wall_width_cm)} cm` : ""}
              </span>
            </div>
          </li>
        ); })}
      </ul>
      {!doc.rooms.length && <p className="muted">No rooms yet.</p>}
    </main>
  );
}
