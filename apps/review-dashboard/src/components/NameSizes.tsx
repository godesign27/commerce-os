import { useEffect, useRef, useState } from "react";
import { api, NameSize } from "../api";
import { Drawer } from "./Drawer";

// "Sizes from file names": every piece with no saved size whose file name carries one ("Animal Art 16x20_0005_Lion.jpg",
// read as inches). The list is shown first, every piece ticked; Save writes the size for the ticked ones, the
// same as saving it on About this piece. A piece that has a size by then keeps it.
export function NameSizes({ onSaved }: { onSaved: () => void }) {
  const [pieces, setPieces] = useState<NameSize[] | null>(null);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const load = () => api.nameSizes().then((r) => { setPieces(r.pieces); return r.pieces; }).catch((e) => { setError(String(e.message || e)); return []; });
  useEffect(() => { load(); }, []);                          // eslint-disable-line react-hooks/exhaustive-deps

  async function show() {
    setNote(null); setError(null);
    const list = await load();
    setPicked(new Set(list.map((p) => p.id)));
    setOpen(true);
  }
  async function save() {
    setBusy(true); setError(null);
    try {
      const r = await api.saveNameSizes([...picked]);
      setNote(`Saved the size for ${r.saved.length} piece${r.saved.length === 1 ? "" : "s"}.`
        + (r.skipped.length ? ` Left ${r.skipped.length} as they were: ${r.skipped.map((s) => s.reason).join("; ")}.` : "")
        + " Redraft drafted pieces to use it in the copy.");
      setOpen(false);
      await load();
      onSaved();
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const all = !!pieces && picked.size === pieces.length;

  if (!pieces?.length && !note) return null;
  return (<>
    {!!pieces?.length && <button ref={opener} className="secondary" onClick={show} aria-haspopup="dialog" aria-expanded={open}>
      Sizes from file names ({pieces.length})</button>}
    {note && <span className="muted small" role="status">{note}</span>}
    {open && pieces && (
      <Drawer title="Sizes from file names" onClose={() => setOpen(false)} busy={busy} opener={opener} className="name-sizes">
        <p className="small muted">These pieces have no size yet, and their file names carry one. Each is read as inches
          unless the name says cm. Untick any that are wrong, then save. You can change a size later under About this piece.</p>
        <label className="small inline"><input type="checkbox" checked={all}
          onChange={() => setPicked(all ? new Set() : new Set(pieces.map((p) => p.id)))} /> All {pieces.length}</label>
        <ul className="name-size-list">
          {pieces.map((p) => (
            <li key={p.id}>
              <label className="inline">
                <input type="checkbox" checked={picked.has(p.id)} onChange={() => toggle(p.id)} />
                {p.image && <img src={`/${p.image}`} alt="" loading="lazy" />}
                <span><strong>{p.size}</strong><span className="small muted"> {p.source}</span></span>
              </label>
            </li>
          ))}
        </ul>
        <div className="row section-actions">
          <button disabled={!picked.size || busy} onClick={save}>
            {busy ? "Saving…" : `Save ${picked.size} size${picked.size === 1 ? "" : "s"}`}</button>
          <button className="secondary" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
        </div>
        {error && <p className="error">{error}</p>}
      </Drawer>
    )}
  </>);
}
