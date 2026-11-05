import { useEffect, useState } from "react";
import { api, HomeDoc } from "../api";
import { ago } from "./Photos";

// The start page: which store is connected, and where each area stands.
function Stat({ n, label, tone }: { n: number; label: string; tone?: "warn" | "ok" }) {
  return <div className={`stat ${tone && n > 0 ? tone : ""}`}><strong>{n}</strong><span>{label}</span></div>;
}

function AreaCard({ href, title, line, children }: { href: string; title: string; line: string; children: React.ReactNode }) {
  return (
    <li className="area">
      <a href={href}>
        <h2>{title} <span aria-hidden="true">→</span></h2>
        <div className="stats">{children}</div>
        <p className="muted small">{line}</p>
      </a>
    </li>
  );
}

export function Home({ tick }: { tick: number }) {
  const [d, setD] = useState<HomeDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.home().then(setD).catch((e) => setError(String(e.message))); }, [tick]);
  if (!d) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const { store, photos: p, listings: l, rooms: r, learning: t } = d;
  const left = d.onboarding.steps.filter((s) => !s.done && s.id !== "photos").length;

  const photoLine = p.to_review ? "Some photos need your review." : p.ready ? "Accepted photos are ready to draft." : p.total ? "Nothing waiting on you." : "Add photos to the inbox to begin.";
  const publishLine = l.publish_problems ? "A publish needs a look." : l.to_publish ? "Approved listings are ready to publish." : l.published ? "Nothing waiting on you." : "Listings you approve for the store appear here.";
  const listingLine = l.out_of_date ? "Some approvals went out of date: check them again." : l.ready ? "Some are ready for your approval."
    : l.blocked ? "Some need a price or other facts." : l.drafted ? "Nothing waiting on you." : "Drafts appear here once photos are accepted.";

  return (
    <main className="page">
      {store.connected ? (
        <section className="store-card connected" aria-label="Connected store">
          <div>
            <p className="muted small">Connected store</p>
            <h1>{store.display_name}</h1>
            <p className="small">{store.site_kind === "artist" ? "Artist site" : "Product site"}{store.provider ? ` · ${store.provider}` : ""} · {store.products} products ·
              {" "}catalog read {ago(store.read_at)}</p>
          </div>
          <div className="store-side">
            <span className="badge ok">✓ Read only</span>
            <p className="muted small">Commerce OS can read this store's catalog. It can't change anything there.</p>
          </div>
        </section>
      ) : (
        <section className="store-card empty" aria-label="No store connected">
          <div>
            <h1>No store connected yet</h1>
            <p className="small">Connect your store so Commerce OS can use its categories and spot pieces you already sell. It only ever reads.</p>
          </div>
          <a className="button-link" href="#/start">{store.display_name ? "Finish connecting" : "Connect a store"}</a>
        </section>
      )}
      {store.connected && left > 0 && (
        <p className="banner">{left} setup step{left > 1 ? "s" : ""} left. <a href="#/start">Finish getting started →</a></p>
      )}
      <ul className="areas">
        <AreaCard href="#/photos" title="Photos" line={photoLine}>
          <Stat n={p.total} label="in all" /><Stat n={p.to_review} label="to review" tone="warn" /><Stat n={p.ready} label="ready to draft" />
          <Stat n={d.inbox.new} label="new in inbox" tone="warn" />
        </AreaCard>
        <AreaCard href="#/listings" title="Listings" line={listingLine}>
          <Stat n={l.drafted} label="drafted" /><Stat n={l.blocked} label="need facts" tone="warn" /><Stat n={l.ready} label="ready to approve" tone="warn" />
          <Stat n={l.approved} label="approved" tone="ok" />
        </AreaCard>
        <AreaCard href="#/publish" title="Publish" line={publishLine}>
          <Stat n={l.to_publish} label="ready to publish" tone="warn" /><Stat n={l.published} label="in test store" tone="ok" />
          {l.publish_problems > 0 && <Stat n={l.publish_problems} label="need a look" tone="warn" />}
        </AreaCard>
        <AreaCard href="#/rooms" title="Rooms" line={r.total ? (r.need_attention ? "Some rooms need setting up." : "Rooms are ready to hang work in.") : "Add a room to show work on a wall."}>
          <Stat n={r.total} label="in all" /><Stat n={r.ready} label="ready" tone="ok" /><Stat n={r.need_attention} label="need setup" tone="warn" />
        </AreaCard>
        <AreaCard href="#/learning" title="Learning" line={t.proposed_lessons ? "Lessons are waiting for your answer." : "Commerce OS learns from what you change in drafts."}>
          <Stat n={t.approvals} label="approvals learned from" /><Stat n={t.proposed_lessons} label="lessons to review" tone="warn" />
        </AreaCard>
      </ul>
      <p className="muted small">{d.publishing.kill_switch.on ? "Writing is switched off. " : ""}{d.publishing.worker.running ? "" : "The publishing worker isn't running. "}
        Publishing only reaches the {d.publishing.target.toLowerCase()} on this computer: {store.display_name || "your store"} itself can't be changed yet.</p>
    </main>
  );
}
