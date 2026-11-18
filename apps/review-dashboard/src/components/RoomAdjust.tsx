import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

// Size and place a piece on its room view (B-079). The outline is where the frame is now: drag it to move,
// drag its corner to resize, or use the keyboard. Resizing is for this piece in this room only; moving sets
// where art hangs in this room for every piece. Nothing changes until Save, which hangs it again.

export const MIN_SCALE = 0.25, MAX_SCALE = 4;
const STEP = 0.01, BIG_STEP = 0.05, GROW = 1.05;
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export interface Adjustment { scale?: number; centre?: [number, number] | null }   // centre null: the middle of the wall

export function RoomAdjust({ image, alt, corners, scale, room, placed, busy, onSave, onCancel }: {
  image: string; alt: string; corners: [number, number][]; scale: number; room: string; placed: boolean; busy: boolean;
  onSave: (a: Adjustment) => void; onCancel: () => void;
}) {
  const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]);
  const w0 = Math.max(...xs) - Math.min(...xs), h0 = Math.max(...ys) - Math.min(...ys);
  const c0: [number, number] = [(Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2];
  const [centre, setCentre] = useState<[number, number]>(c0);
  const [size, setSize] = useState(scale);                    // the piece's size, as a multiple of its real size
  const stage = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ kind: "move" | "size"; x: number; y: number; centre: [number, number]; size: number; dist: number } | null>(null);
  const k = size / scale, w = w0 * k, h = h0 * k;
  const moved = Math.abs(centre[0] - c0[0]) > 1e-4 || Math.abs(centre[1] - c0[1]) > 1e-4;
  const resized = Math.abs(size - scale) > 1e-3;

  function start(e: PointerEvent, kind: "move" | "size") {
    if (busy) return;
    e.preventDefault(); e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    const r = stage.current!.getBoundingClientRect();
    const dist = Math.hypot(e.clientX - (r.left + centre[0] * r.width), e.clientY - (r.top + centre[1] * r.height));
    drag.current = { kind, x: e.clientX, y: e.clientY, centre, size, dist: Math.max(dist, 1) };
  }
  function move(e: PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const r = stage.current!.getBoundingClientRect();
    if (d.kind === "move") {
      setCentre([clamp(d.centre[0] + (e.clientX - d.x) / r.width, 0, 1), clamp(d.centre[1] + (e.clientY - d.y) / r.height, 0, 1)]);
    } else {
      const dist = Math.hypot(e.clientX - (r.left + d.centre[0] * r.width), e.clientY - (r.top + d.centre[1] * r.height));
      setSize(clamp(d.size * dist / d.dist, MIN_SCALE, MAX_SCALE));
    }
  }
  function end() { drag.current = null; }
  function key(e: KeyboardEvent) {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const by: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (by[e.key]) setCentre(([x, y]) => [clamp(x + by[e.key][0], 0, 1), clamp(y + by[e.key][1], 0, 1)]);
    else if (e.key === "+" || e.key === "=") setSize((s) => clamp(s * GROW, MIN_SCALE, MAX_SCALE));
    else if (e.key === "-" || e.key === "_") setSize((s) => clamp(s / GROW, MIN_SCALE, MAX_SCALE));
    else if (e.key === "Escape") onCancel();
    else return;
    e.preventDefault();
  }

  return (
    <div className="room-adjust">
      <div className="room-adjust-stage" ref={stage}>
        <img src={image} alt={alt} draggable={false} />
        <div className="room-adjust-box" role="slider" tabIndex={0} aria-label="The piece on the wall"
             aria-valuemin={MIN_SCALE} aria-valuemax={MAX_SCALE} aria-valuenow={Number(size.toFixed(2))}
             aria-valuetext={`${size.toFixed(2)} times its real size`}
             aria-describedby="room-adjust-help"
             style={{ left: `${(centre[0] - w / 2) * 100}%`, top: `${(centre[1] - h / 2) * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}
             onPointerDown={(e) => start(e, "move")} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={key}>
          <span className="room-adjust-handle" aria-hidden="true" onPointerDown={(e) => start(e, "size")} onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
        </div>
      </div>
      <p id="room-adjust-help" className="small muted">
        Drag the outline to move it and its corner to resize it, or use the arrow keys and + or −. The size is for this piece
        in {room}; where it hangs is for every piece in {room}.
      </p>
      <div className="row between small">
        <span><strong>{size.toFixed(2)}×</strong> its real size</span>
        <span className="row">
          <button type="button" className="link" disabled={busy || Math.abs(size - 1) < 1e-3} onClick={() => setSize(1)}>Real size</button>
          <button type="button" className="link" disabled={busy || !placed} onClick={() => onSave({ centre: null, ...(resized ? { scale: size } : {}) })}>Centre on the wall</button>
        </span>
      </div>
      <div className="row section-actions">
        <button type="button" disabled={busy || (!moved && !resized)}
                onClick={() => onSave({ ...(resized ? { scale: size } : {}), ...(moved ? { centre } : {}) })}>
          {busy ? "Hanging…" : "Save"}</button>
        <button type="button" className="secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
