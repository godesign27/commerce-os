import { useEffect, useState } from "react";
import { api, HomeDoc } from "../api";
import { ago } from "./Photos";

// The start page (B-074): the one thing to do next, then every piece under its status, drawn as the piece itself.
// Each count is written out, and zeros stay, so the shape is readable without colour.
export function Home({ tick }: { tick: number }) {
  const [d, setD] = useState<HomeDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.home().then(setD).catch((e) => setError(String(e.message))); }, [tick]);
  if (!d) return <main className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const { store, photos: p, listings: l, rooms: r, learning: t } = d;
  const left = d.onboarding.steps.filter((s) => !s.done && s.id !== "photos").length;
  const off = d.pieces.filter((x) => x.status.id === "rejected").length;
  const here = (id: string) => d.pieces.filter((x) => x.status.id === id || (id === "published" && x.status.id === "publishing"));
  const problems = d.pieces.filter((x) => x.status.id === "needs-look");

  return (
    <main className="page">
      {!store.connected && (
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
      {d.next ? (
        <section className="next-step home-next" aria-label="Next step">
          <div className="next-text">
            <h1>{d.next.headline}</h1>
            <p className="muted">{d.next.detail}</p>
          </div>
          <a className="button-link" href={d.next.href}>{d.next.label}</a>
        </section>
      ) : (
        <section className="next-step home-next" aria-label="Next step">
          <div className="next-text"><h1>Nothing is waiting on you</h1>
            <p className="muted">{d.pieces.length ? "Every piece is as far along as it can go." : "Add photos to the inbox to begin."}</p></div>
          <a className="button-link" href="#/photos">Go to Photos</a>
        </section>
      )}

      <section aria-labelledby="pipe-h">
        <h2 id="pipe-h">Where every piece is</h2>
        <div className="pipeline">
          {d.pipeline.map((s) => {
            const pieces = here(s.id);
            return (
              <section key={s.id} className={`stage ${pieces.length && s.tone === "todo" ? "needs-you" : ""}`} style={{ flexGrow: Math.min(Math.max(pieces.length, 3), 16) }}>
                <h3>{s.label}</h3>
                <p className="stage-n">{pieces.length}</p>
                <div className="stage-pieces">
                  {pieces.map((x) => (
                    <a key={x.id} href={x.status.id === "ready-to-draft" || x.status.id === "review-photo" ? `#/photos/${x.id}` : `#/listings/${x.id}`} title={`${x.title || x.source}: ${x.status.label}`}>
                      {x.thumb ? <img src={`/${x.thumb}`} alt={x.title || x.source} loading="lazy" /> : <span className="no-thumb">{x.title || x.source}</span>}
                    </a>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
        {(problems.length > 0 || off > 0) && (
          <p className="small">
            {problems.length > 0 && <span className="warn-text">{problems.length} need{problems.length === 1 ? "s" : ""} a look: {problems.map((x, i) => <span key={x.id}>{i > 0 && ", "}<a href={`#/listings/${x.id}`}>{x.title || x.source}</a></span>)}. </span>}
            {off > 0 && <a href="#/photos">{off} rejected</a>}
          </p>
        )}
      </section>

      <div className="home-more">
        <section>
          <h2>Also worth a look</h2>
          <ul className="plain">
            <li><a href="#/photos">Photos</a>: {p.total} in all, {p.to_review} to review, {p.ready} ready to draft, {d.inbox.new} new in the inbox</li>
            <li><a href="#/listings">Listings</a>: {l.drafted} drafted, {l.copy_approved} with approved copy, {l.approved} approved for the store</li>
            <li><a href="#/rooms">Rooms</a>: {r.total} in all, {r.ready} ready, {r.need_attention} need setting up</li>
            <li><a href="#/learning">Learning</a>: learned from {t.approvals} approval{t.approvals === 1 ? "" : "s"}, {t.proposed_lessons} lesson{t.proposed_lessons === 1 ? "" : "s"} to review</li>
          </ul>
        </section>
        <section>
          <h2>{store.display_name || "Your store"}</h2>
          {store.connected ? (
            <p className="small">{store.site_kind === "artist" ? "Artist site" : "Product site"}{store.provider ? `, ${store.provider}` : ""}. {store.products} products, catalog read {ago(store.read_at)}.
              {" "}Commerce OS can read this store's catalog. It can't change anything there.</p>
          ) : <p className="small muted">Not connected yet.</p>}
          <p className="small"><a href="#/publish">Publish</a>: {l.to_publish} ready, {l.published} in the test store{l.publish_problems ? `, ${l.publish_problems} need a look` : ""}.
            {" "}{d.publishing.kill_switch.on ? "Writing is switched off. " : ""}{d.publishing.worker.running ? "" : "The publishing worker isn't running. "}
            Publishing only reaches the {d.publishing.target.toLowerCase()} on this computer: {store.display_name || "your store"} itself can't be changed yet.</p>
        </section>
      </div>
    </main>
  );
}
