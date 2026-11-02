import { useRef, useState } from "react";
import { Pt } from "../api";

// Four draggable corners over an image, in the image's own pixels: the photo page's crop outline (B-062)
// and the room page's hanging area (B-063). Drag a corner, click to bring the nearest one there, or Tab to
// a corner and nudge it with the arrow keys (Shift for bigger steps).
const STEP = 10;                       // arrow-key nudge, in image pixels (×10 with Shift)
const NAMES = ["top-left", "top-right", "bottom-right", "bottom-left"];

export function same(a: Pt[] | null, b: Pt[] | null) { return JSON.stringify(a) === JSON.stringify(b); }

export function CornerEditor({ src, alt, size, pts, onChange, ghost, label }: {
  src: string; alt: string; size: [number, number]; pts: Pt[] | null; onChange: (pts: Pt[]) => void;
  ghost?: Pt[] | null; label: string;
}) {
  const [W, H] = size;
  const [active, setActive] = useState(0);
  const svg = useRef<SVGSVGElement | null>(null);
  const drag = useRef(-1);
  const px = W / 600;                                   // handles and lines stay a constant size on screen

  function toImage(ev: React.PointerEvent): Pt {
    const box = svg.current!.getBoundingClientRect();
    return [Math.max(0, Math.min(W, (ev.clientX - box.left) / box.width * W)),
            Math.max(0, Math.min(H, (ev.clientY - box.top) / box.height * H))];
  }
  function down(ev: React.PointerEvent) {
    if (!pts) return;
    const hit = (ev.target as Element).getAttribute("data-i");
    let i = hit === null ? -1 : +hit;
    if (i < 0) {                                         // click anywhere: bring the nearest corner there
      const q = toImage(ev);
      i = pts.reduce((best, c, k) => ((c[0]-q[0])**2 + (c[1]-q[1])**2 < (pts[best][0]-q[0])**2 + (pts[best][1]-q[1])**2 ? k : best), 0);
      onChange(pts.map((c, k) => k === i ? q : c));
    }
    drag.current = i; setActive(i);
    svg.current!.setPointerCapture(ev.pointerId);
  }
  function move(ev: React.PointerEvent) {
    if (drag.current < 0 || !pts) return;
    const q = toImage(ev);
    onChange(pts.map((c, k) => k === drag.current ? q : c));
  }
  function key(ev: React.KeyboardEvent, i: number) {
    const d = ({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] } as Record<string, number[]>)[ev.key];
    if (!d || !pts) return;
    ev.preventDefault();
    const s = ev.shiftKey ? STEP * 10 : STEP;
    onChange(pts.map((c, k) => k === i ? [Math.max(0, Math.min(W, c[0] + d[0] * s)), Math.max(0, Math.min(H, c[1] + d[1] * s))] : c));
  }

  return (
    <div className="corner-stage">
      <img src={src} alt={alt} />
      {pts && (
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} onPointerDown={down} onPointerMove={move}
             onPointerUp={() => { drag.current = -1; }} role="group" aria-label={label}>
          {ghost && (
            <polygon points={ghost.map((q) => q.join(",")).join(" ")} className="outline-found"
                     strokeWidth={1.5 * px} strokeDasharray={`${8 * px} ${6 * px}`} />)}
          <polygon points={pts.map((q) => q.join(",")).join(" ")} className="outline" strokeWidth={2.5 * px} />
          {pts.map((q, i) => (
            <circle key={i} data-i={i} cx={q[0]} cy={q[1]} r={12 * px} strokeWidth={3 * px}
                    className={`handle ${active === i ? "on" : ""}`} tabIndex={0} role="slider"
                    aria-label={`${NAMES[i]} corner`} aria-valuetext={`x ${Math.round(q[0])}, y ${Math.round(q[1])}`}
                    onFocus={() => setActive(i)} onKeyDown={(e) => key(e, i)} />
          ))}
        </svg>
      )}
    </div>
  );
}
