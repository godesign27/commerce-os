import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVITY_EVENT, Activity, ActivityJob, ActivityPublish, api } from "../api";

// The task bar (B-077): on every page, what's being processed and how far it's got, so nothing runs out of sight.
// It looks every 2 seconds while something is moving and every 10 otherwise, and at once after any change you make.
const BUSY_MS = 2000;
const IDLE_MS = 10000;
const CLEARED_KEY = "commerce-os.taskbar.cleared";

// What you've cleared: publishes that finished up to this time, and these finished jobs.
interface Cleared { at: string; jobs: string[] }
function readCleared(): Cleared {
  try {
    const c = JSON.parse(localStorage.getItem(CLEARED_KEY) || "null");
    if (c && typeof c.at === "string" && Array.isArray(c.jobs)) return c;
  } catch { /* unreadable or blocked: start with nothing cleared */ }
  return { at: "", jobs: [] };
}

function held(p: ActivityPublish) { return p.active && p.stage.startsWith("Held"); }
function failed(p: ActivityPublish) { return p.state === "FAILED" || p.state === "OUTCOME_UNKNOWN"; }

function summary(a: Activity, pubs: ActivityPublish[], jobs: ActivityJob[]): { text: string; tone: "busy" | "held" | "done" | "bad" } {
  const moving = pubs.filter((p) => p.active);
  const running = jobs.find((j) => j.running);
  if (moving.length) {
    const finished = pubs.length - moving.length;
    const now = moving.find((p) => !held(p)) || moving[0];
    if (held(now)) return { text: `${moving.length} waiting to publish. ${now.stage}`, tone: "held" };
    return { text: `Publishing ${finished + 1} of ${pubs.length} to the ${a.target.toLowerCase()}: ${now.title}, ${now.stage.toLowerCase()}`, tone: "busy" };
  }
  if (running) {
    const of = running.total ? `: ${running.done} of ${running.total}` : "";
    return { text: `${running.label}${of}`, tone: "busy" };
  }
  const bad = pubs.filter(failed).length + jobs.filter((j) => j.error).length;
  const ok = pubs.length - pubs.filter(failed).length;
  const parts = [];
  if (ok) parts.push(`${ok} published to the ${a.target.toLowerCase()}${a.live ? " as Drafts" : ""}`);
  const jobsDone = jobs.filter((j) => !j.error).length;
  if (jobsDone) parts.push(`${jobsDone} ${jobsDone === 1 ? "task" : "tasks"} finished`);
  if (bad) parts.push(`${bad} need${bad === 1 ? "s" : ""} a look`);
  return { text: `Done: ${parts.join(", ")}`, tone: bad ? "bad" : "done" };
}

export function TaskBar({ onSettled }: { onSettled: () => void }) {
  const [a, setA] = useState<Activity | null>(null);
  const [open, setOpen] = useState(false);
  const [cleared, setCleared] = useState(readCleared);
  const wasActive = useRef(false);
  const timer = useRef<number>();

  const look = useCallback(() => {
    window.clearTimeout(timer.current);
    if (document.hidden) return;
    api.activity().then((next) => {
      setA(next);
      if (wasActive.current && !next.active) onSettled();        // let the page show what just finished
      wasActive.current = next.active;
      timer.current = window.setTimeout(look, next.active ? BUSY_MS : IDLE_MS);
    }).catch(() => { timer.current = window.setTimeout(look, IDLE_MS); });
  }, [onSettled]);

  useEffect(() => {
    look();
    window.addEventListener(ACTIVITY_EVENT, look);
    document.addEventListener("visibilitychange", look);
    return () => {
      window.clearTimeout(timer.current);
      window.removeEventListener(ACTIVITY_EVENT, look);
      document.removeEventListener("visibilitychange", look);
    };
  }, [look]);

  if (!a) return null;
  // Finished rows stay until cleared; anything still moving always shows.
  const pubs = a.publishing.filter((p) => p.active || p.at > cleared.at);
  const jobs = a.jobs.filter((j) => j.running || !cleared.jobs.includes(j.id));
  if (!pubs.length && !jobs.length) return null;
  const s = summary(a, pubs, jobs);
  const clear = () => {
    const next = { at: pubs.reduce((m, p) => (p.at > m ? p.at : m), cleared.at),
      jobs: [...cleared.jobs, ...jobs.filter((j) => !j.running).map((j) => j.id)].slice(-20) };
    setCleared(next); setOpen(false);
    try { localStorage.setItem(CLEARED_KEY, JSON.stringify(next)); } catch { /* private window: it just won't be remembered */ }
  };

  return (
    <section className={`taskbar ${s.tone}`} aria-label="Tasks in progress">
      <div className="taskbar-line">
        <span className="taskbar-dot" aria-hidden="true" />
        <p className="taskbar-summary" role="status" aria-live="polite">{s.text}</p>
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide" : `Show ${pubs.length + jobs.length}`}</button>
        {!a.active && <button className="link" onClick={clear}>Clear</button>}
      </div>
      {open && (
        <ul className="taskbar-list">
          {jobs.map((j) => (
            <li key={j.id} className={j.error ? "bad" : j.running ? "busy" : "done"}>
              <span className="taskbar-mark" aria-hidden="true">{j.error ? "!" : j.running ? "•" : "✓"}</span>
              <span className="taskbar-what">{j.label}</span>
              <span className="taskbar-stage">
                {j.error ? j.error : j.running ? (j.total ? `${j.done} of ${j.total}` : "Starting") : "Finished"}
                {j.running && j.total > 0 && <progress value={j.done} max={j.total} aria-label={`${j.label} progress`} />}
              </span>
            </li>
          ))}
          {pubs.map((p) => (
            <li key={p.id} className={failed(p) ? "bad" : held(p) ? "held" : p.active ? "busy" : "done"}>
              <span className="taskbar-mark" aria-hidden="true">{failed(p) ? "!" : p.active ? "•" : "✓"}</span>
              <a className="taskbar-what" href={`#/listings/${p.id}`}>{p.title}</a>
              <span className="taskbar-stage">{p.stage}{p.detail && failed(p) ? `: ${p.detail}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
