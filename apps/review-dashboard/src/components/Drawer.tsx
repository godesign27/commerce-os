import { ReactNode, RefObject, useEffect, useId, useRef } from "react";

// A panel that slides in from the right over the page: Add a room (Rooms page) and Change room (photo page).
// Escape, the ✕, or a click on the dimmed page closes it (not while `busy`); Tab stays inside it; the page
// behind doesn't scroll; on close the keyboard goes back to whatever opened it.
const FOCUSABLE = "input, select, textarea, button, a[href], [tabindex='0']";

export function Drawer({ title, onClose, busy = false, focus, opener: openerRef, className = "", children }: {
  title: string; onClose: () => void; busy?: boolean; focus?: string; className?: string; children: ReactNode;
  opener?: RefObject<HTMLElement | null>;      // the button that opened it (Safari doesn't focus a clicked button)
}) {
  const panel = useRef<HTMLElement | null>(null);
  const close = useRef(onClose);
  close.current = busy ? () => {} : onClose;
  const titleId = useId();

  useEffect(() => {
    const opener = openerRef?.current || (document.activeElement as HTMLElement | null);
    const first = (focus && panel.current?.querySelector<HTMLElement>(focus)) || panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close.current(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const els = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((x) => !x.hasAttribute("disabled"));
      if (!els.length) return;
      const [a, z] = [els[0], els[els.length - 1]];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      setTimeout(() => opener?.focus(), 0);                  // back to the button that opened it, once it's enabled again
    };
  }, []);                                                    // eslint-disable-line react-hooks/exhaustive-deps

  return (<>
    <div className="drawer-backdrop" onClick={() => close.current()} aria-hidden="true" />
    <aside ref={panel} className={`drawer ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="row between drawer-head">
        <h2 id={titleId}>{title}</h2>
        <button className="secondary icon" onClick={() => close.current()} disabled={busy} aria-label="Close">✕</button>
      </div>
      {children}
    </aside>
  </>);
}
