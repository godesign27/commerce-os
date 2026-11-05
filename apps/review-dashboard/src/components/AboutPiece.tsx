import { useState } from "react";
import { api } from "../api";

// "About this piece": the facts only the owner knows (series, edition, medium, size). One source for the
// listing page and the photo page: both save through api.saveListing to the same listing record. The size
// is entered as width × height with a unit, and written as "16 x 20 in", which both the copy checks and the
// room views read. A size without a unit is never saved from here: "16 x 20" could be inches or cm.
export type Facts = { edition?: string; medium?: string; dimensions?: string; price?: string; sold_as?: string };
type Unit = "in" | "cm";
// Copied from packages/drafting/store.py (PRICE): change both.
export const PRICE = /^\$?\s*(\d{1,3}(?:,\d{3})+|\d{1,7})(\.\d{1,2})?$/;
const listWords = (xs: string[]) => xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
const SHAPE = /^\s*(\d+(?:\.\d+)?)\s*(in|inch|inches|"|cm|mm)?\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)\s*(in|inch|inches|"|cm|mm)?\s*$/i;

export function splitSize(text: string): { w: string; h: string; unit: Unit | ""; fits: boolean } {
  const m = SHAPE.exec(text || "");
  if (!m) return { w: "", h: "", unit: "", fits: !text.trim() };
  const [, a, u1, b, u2] = m;
  const u = (u2 || u1 || "").toLowerCase();
  if (u === "mm") return { w: String(+a / 10), h: String(+b / 10), unit: "cm", fits: true };
  return { w: a, h: b, unit: u === "cm" ? "cm" : u ? "in" : "", fits: true };
}

export function joinSize(w: string, h: string, unit: Unit | ""): string {
  return w.trim() && h.trim() && unit ? `${+w} x ${+h} ${unit}` : "";
}

// Medium, size, price and what it's sold as are what a listing can't do without; they're laid out as steps
// like the room set-up, each ticked once saved. Series and edition are extra. A size in the file name
// ("Animal Art 16x20_0005_Lion.jpg") is pre-filled as inches, for the owner to check and save. Price and
// "sold as" go to the storefront only: they never reach the copy drafts.
export function AboutPiece({ itemId, series: series0, facts: facts0, onSaved, note, sizeFromName, tierTypes = [] }: {
  itemId: string; series: string; facts: Facts; onSaved: () => Promise<void> | void;
  note?: string;                        // what saving means for the copy, e.g. "Redraft to use it in the copy."
  sizeFromName?: string | null;         // a size read from the file name, pre-filled when none is saved
  tierTypes?: string[];                 // the storefront's tier types ("Original", "Print", …) for "Sold as"
}) {
  const start = { series: series0 || "", edition: facts0.edition || "", medium: facts0.medium || "", size: facts0.dimensions || "",
                  price: facts0.price || "", soldAs: facts0.sold_as || "" };
  const s0 = splitSize(start.size);
  const fromName = !start.size && sizeFromName ? splitSize(sizeFromName) : null;
  const first = fromName?.fits ? fromName : s0;
  const [series, setSeries] = useState(start.series);
  const [edition, setEdition] = useState(start.edition);
  const [medium, setMedium] = useState(start.medium);
  const [price, setPrice] = useState(start.price);
  const [soldAs, setSoldAs] = useState(start.soldAs);
  const [w, setW] = useState(first.w); const [h, setH] = useState(first.h);
  const [unit, setUnit] = useState<Unit | "">(first.unit);
  const [sizeTouched, setSizeTouched] = useState(!!fromName?.fits);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const size = sizeTouched ? joinSize(w, h, unit) : start.size;   // an untouched odd size is kept as it is
  const half = sizeTouched && (!!w.trim() !== !!h.trim() || (!!w.trim() && !unit));
  const bad = sizeTouched && [w, h].some((v) => v.trim() !== "" && !(+v > 0));
  const badPrice = !!price.trim() && !PRICE.test(price.trim());
  const dirty = series !== start.series || edition !== start.edition || medium !== start.medium || size !== start.size
    || price !== start.price || soldAs !== start.soldAs;
  const touch = (f: () => void) => { f(); setSizeTouched(true); setMsg(null); };
  const showingName = !!fromName?.fits && size === joinSize(fromName.w, fromName.h, fromName.unit);
  const needs = [
    { id: "medium", label: "Medium", saved: !!start.medium.trim(), filled: !!medium.trim(), changed: medium !== start.medium },
    { id: "size", label: "Size", saved: !!start.size && s0.fits && !!s0.unit, filled: !!size && !half && !bad, changed: size !== start.size },
    { id: "price", label: "Price", saved: !!start.price, filled: !!price.trim() && !badPrice, changed: price !== start.price },
    { id: "sold_as", label: "Sold as", saved: !!start.soldAs, filled: !!soldAs, changed: soldAs !== start.soldAs },
  ];
  const toSupply = needs.filter((n) => !n.saved).length;
  const todo = needs.filter((n) => !n.filled).map((n) => n.label.toLowerCase());

  function reset() {
    setSeries(start.series); setEdition(start.edition); setMedium(start.medium); setPrice(start.price); setSoldAs(start.soldAs);
    setW(s0.w); setH(s0.h); setUnit(s0.unit); setSizeTouched(false); setMsg(null);   // drops the file-name size too
  }
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await api.saveListing(itemId, { series, facts: { edition, medium, dimensions: size, price, sold_as: soldAs } });
      setSizeTouched(false);
      await onSaved();
      setMsg(`Saved.${note ? ` ${note}` : ""}`);
    } catch (e) { setMsg(String((e as Error).message)); }
    setBusy(false);
  }
  const mark = (n: typeof needs[number], i: number) => n.saved && !n.changed ? "✓" : String(i + 1);
  const cls = (n: typeof needs[number]) => n.saved && !n.changed ? "done" : n.filled ? "pending" : "";

  return (
    <section className={`panel details ${dirty ? "dirty" : ""}`} aria-labelledby={`about-${itemId}`}>
      <h2 id={`about-${itemId}`}>About this piece{" "}
        {toSupply ? <span className="badge bad">{toSupply} to supply</span> : <span className="badge ok">✓ Supplied</span>}{" "}
        {dirty && <span className="badge warn">Not saved</span>}</h2>
      <p className="muted small">Only what you know. The copy can mention medium, size or edition only once they're here,
        and the size sets how big the piece hangs in a room. Price and "sold as" go to the storefront, never into the copy.</p>
      <ol className="steps">
        <li className={cls(needs[0])}>
          <span className="step-n" aria-hidden="true">{mark(needs[0], 0)}</span>
          <div>
            <label htmlFor={`m-${itemId}`}><strong>Medium</strong></label>
            <input id={`m-${itemId}`} value={medium} onChange={(e) => { setMedium(e.target.value); setMsg(null); }} placeholder="e.g. acrylic on canvas" />
          </div>
        </li>
        <li className={cls(needs[1])}>
          <span className="step-n" aria-hidden="true">{mark(needs[1], 1)}</span>
          <div>
            <fieldset className="size-row">
              <legend><strong>Size</strong> <span className="muted small">(the artwork, without a frame)</span></legend>
              <label className="sr-only" htmlFor={`w-${itemId}`}>Width</label>
              <input id={`w-${itemId}`} type="number" min={0} step="any" inputMode="decimal" placeholder="Width" value={w}
                     onChange={(e) => touch(() => setW(e.target.value))} aria-invalid={bad || undefined} />
              <span aria-hidden="true">×</span>
              <label className="sr-only" htmlFor={`h-${itemId}`}>Height</label>
              <input id={`h-${itemId}`} type="number" min={0} step="any" inputMode="decimal" placeholder="Height" value={h}
                     onChange={(e) => touch(() => setH(e.target.value))} aria-invalid={bad || undefined} />
              <select aria-label="Unit" value={unit} onChange={(e) => touch(() => setUnit(e.target.value as Unit | ""))}>
                {!unit && <option value="">Unit…</option>}
                <option value="in">inches</option><option value="cm">cm</option>
              </select>
              {(w || h || start.size) && <button type="button" className="link" onClick={() => touch(() => { setW(""); setH(""); })}>Clear</button>}
            </fieldset>
            {showingName && <p className="small banner-inline">Read from the file name as {sizeFromName}. Check it, then press <strong>Save details</strong>.</p>}
            {!sizeTouched && start.size && !s0.fits && <p className="small warn-text">Saved as "{start.size}", which isn't width × height. Enter it above to replace it.</p>}
            {!sizeTouched && start.size && s0.fits && !s0.unit && <p className="small warn-text">Saved as "{start.size}" with no unit: choose inches or cm so it hangs at its real size.</p>}
            {half && <p className="small warn-text">{!unit ? "Choose inches or cm." : "Give both the width and the height."}</p>}
            {bad && <p className="small warn-text">Width and height are numbers above 0.</p>}
          </div>
        </li>
        <li className={cls(needs[2])}>
          <span className="step-n" aria-hidden="true">{mark(needs[2], 2)}</span>
          <div>
            <label htmlFor={`p-${itemId}`}><strong>Price</strong> <span className="muted small">(US dollars, for the storefront only)</span></label>
            <input id={`p-${itemId}`} inputMode="decimal" value={price} placeholder="e.g. 450" aria-invalid={badPrice || undefined}
                   onChange={(e) => { setPrice(e.target.value); setMsg(null); }} />
            {badPrice && <p className="small warn-text">A dollar amount, like 450 or 1,250.00.</p>}
          </div>
        </li>
        <li className={cls(needs[3])}>
          <span className="step-n" aria-hidden="true">{mark(needs[3], 3)}</span>
          <div>
            <label htmlFor={`t-${itemId}`}><strong>Sold as</strong></label>
            <select id={`t-${itemId}`} value={soldAs} onChange={(e) => { setSoldAs(e.target.value); setMsg(null); }}>
              <option value="">Choose…</option>
              {[...new Set([...tierTypes, ...(start.soldAs ? [start.soldAs] : [])])].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </li>
      </ol>
      <h3 className="small">Also, if you know them</h3>
      <div className="facts">
        <label>Edition
          <select value={edition} onChange={(e) => setEdition(e.target.value)}>
            <option value="">Not said</option><option value="original">Original</option><option value="print">Print</option><option value="both">Original and prints</option>
          </select></label>
        <label>Series <input value={series} onChange={(e) => setSeries(e.target.value)} placeholder="optional" /></label>
      </div>
      {dirty && <p className="small" role="status">{todo.length ? <>Still to supply: {listWords(todo)}.</>
        : toSupply ? <>All filled in. <strong>Save details</strong> to supply them.</> : null}</p>}
      {dirty && (
        <div className="row section-actions">
          <button disabled={busy || half || bad || badPrice} onClick={save}>{busy ? "Saving…" : "Save details"}</button>
          <button className="secondary" disabled={busy} onClick={reset}>Discard</button>
        </div>
      )}
      {!dirty && !toSupply && !msg && <p className="small muted">Medium, size, price and what it's sold as are supplied.</p>}
      {msg && <p className="muted small" role="status">{msg}</p>}
    </section>
  );
}
