import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, State } from "./api";
import { Listings } from "./pages/Listings";
import { ListingDetail } from "./pages/ListingDetail";
import { Brand } from "./pages/Brand";
import { Learning } from "./pages/Learning";
import { Setup } from "./pages/Setup";
import { GettingStarted } from "./pages/GettingStarted";
import { Home } from "./pages/Home";
import { NewPhotos } from "./components/NewPhotos";
import { Photos } from "./pages/Photos";
import { PhotoDetailPage } from "./pages/PhotoDetail";
import { Rooms } from "./pages/Rooms";
import { RoomDetail } from "./pages/RoomDetail";
import "./styles.css";

// A tab left open across a rebuild keeps running the old page, because moving between pages never reloads it.
// On each move, compare the build this tab runs with the one the server now serves, and reload if it changed.
// Unsaved edits are safe: pages that have them ask before you leave.
const BUILD = /\/assets\/index-[^"']+\.js/;
function reloadIfRebuilt() {
  const mine = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]')?.getAttribute("src")?.match(BUILD)?.[0];
  if (!mine) return;                                       // the dev server: nothing to compare
  fetch("/", { cache: "no-store" }).then((r) => r.text()).then((html) => {
    const now = html.match(BUILD)?.[0];
    if (now && now !== mine) location.reload();
  }).catch(() => {});
}

// Hash routes keep the dashboard a set of static files the local API can serve as-is.
function useRoute(): string {
  const [route, setRoute] = useState(() => location.hash.slice(1) || "/home");
  useEffect(() => {
    const on = () => { setRoute(location.hash.slice(1) || "/home"); reloadIfRebuilt(); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

function App() {
  const route = useRoute();
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => api.state().then(setState).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { refresh(); }, [refresh, route]);
  // New photos are announced on every page; a light check, not a page refresh.
  const [inbox, setInbox] = useState(0);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const look = () => { if (!document.hidden) api.inbox().then((i) => setInbox(i.new)).catch(() => undefined); };
    look();
    const timer = setInterval(look, 10000);
    document.addEventListener("visibilitychange", look);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", look); };
  }, [tick]);

  if (error) return <main className="page"><p className="error">Can't reach the local API: {error}</p></main>;
  if (!state) return <main className="page"><p className="muted">Loading…</p></main>;
  const needsStart = !state.onboarding.complete;
  const [, section, id] = route.split("/");
  const nav = [["home", "Home"], ["photos", "Photos"], ["rooms", "Rooms"], ["listings", "Listings"], ["learning", "Learning"]];
  const menu = [["brand", state.site_kind === "product" ? "Brand context" : "Artist context"], ["start", "Getting started"], ["setup", "Voice setup"]];
  let page;
  // Photos and rooms work before setup is finished; listings need the store and the voice.
  if (!section || section === "home") page = <Home tick={tick} />;
  else if (section === "start" || (needsStart && section === "listings")) page = <GettingStarted state={state} onChange={refresh} />;
  else if (section === "setup") page = <Setup state={state} onDone={refresh} />;
  else if (section === "listings" && id) page = <ListingDetail id={id} state={state} onChange={refresh} />;
  else if (section === "brand") page = <Brand state={state} onChange={refresh} />;
  else if (section === "learning") page = <Learning state={state} onChange={refresh} />;
  else if (section === "photos" && id) page = <PhotoDetailPage key={id} id={id} onChange={refresh} />;
  else if (section === "photos") page = <Photos onChange={refresh} />;
  else if (section === "rooms" && id) page = <RoomDetail key={id} id={id} />;
  else if (section === "rooms") page = <Rooms />;
  else page = <Listings state={state} onChange={refresh} />;

  return (
    <>
      <header className="top">
        <div className="top-left">
          <div className="brandmark">Commerce OS <span>{state.onboarding.steps[0].done ? `${state.display_name} · ` : ""}local review</span></div>
          <nav aria-label="Sections">
            {nav.map(([k, label]) => (
              <a key={k} href={`#/${k}`} aria-current={section === k ? "page" : undefined}>
                {label}
                {k === "photos" && inbox > 0 ? <span className="pill" aria-label={`${inbox} new`}>{inbox}</span> : null}
                {k === "learning" && state.brand?.proposed_lessons ? <span className="pill">{state.brand.proposed_lessons}</span> : null}
              </a>
            ))}
          </nav>
        </div>
        <UserMenu name={state.brand?.name || state.display_name} items={menu} section={section} route={route} />
      </header>
      <NewPhotos count={inbox} onDone={() => { refresh(); setTick((t) => t + 1); }} />
      {state.onboarding.complete && !state.key_configured && <div className="banner">There's no Claude API key, so drafting is off. <a href="#/start">Add one →</a></div>}
      {page}
      <footer className="foot">Local only (127.0.0.1). Publishing reaches only a local test store; your real store can't be changed from here.</footer>
    </>
  );
}

// The owner's menu. Local only: there is no sign-in yet (Phase 2), so the avatar is the storefront owner.
function UserMenu({ name, items, section, route }: { name: string; items: string[][]; section: string; route: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
  useEffect(() => setOpen(false), [route]);
  useEffect(() => {
    if (!open) return;
    const click = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", key);
    box.current?.querySelector<HTMLAnchorElement>("[role=menuitem]")?.focus();
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [open]);
  const here = items.some(([k]) => k === section);
  return (
    <div className="user-menu" ref={box}>
      <button ref={button} className={`avatar-button ${here ? "here" : ""}`} aria-haspopup="menu" aria-expanded={open}
        aria-label={`Account menu for ${name}`} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{initials}</span>
        <svg className={`caret ${open ? "up" : ""}`} width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Account">
          <div className="menu-head"><strong>{name}</strong><span className="muted small">Owner · this computer</span></div>
          {items.map(([k, label]) => (
            <a key={k} role="menuitem" href={`#/${k}`} aria-current={section === k ? "page" : undefined}
              onKeyDown={(e) => {
                const all = [...(box.current?.querySelectorAll<HTMLAnchorElement>("[role=menuitem]") || [])];
                const i = all.indexOf(e.currentTarget);
                if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length].focus(); }
                if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length].focus(); }
              }}>{label}</a>
          ))}
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
