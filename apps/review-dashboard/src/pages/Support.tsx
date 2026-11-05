import { State } from "../api";
import { InstallHelp } from "../components/SetupHelp";

// A reminder of how things work (B-076). The steps are drawn in HTML so they still read on a phone.
type Step = { title: string; detail: string; you?: boolean };
const HERE: Step[] = [
  { title: "You approve the listing", detail: "The exact version you saw is locked in. If it changes, you approve it again.", you: true },
  { title: "You press Publish", detail: "This only asks the publishing worker to send it.", you: true },
  { title: "The worker checks once more", detail: "It checks the approved version, the store's structure and the stop switch.", },
  { title: "The worker sends it to the store", detail: "It uses a limited login that can only add new products." },
];
const STORE: Step[] = [
  { title: "Images, then a Draft product", detail: "The store's database refuses any status but Draft from Commerce OS." },
  { title: "The worker reads it back", detail: "It only counts as published once what's in the store matches what you approved." },
  { title: "You review it in store admin", detail: "Edit it, or delete it if it isn't right.", you: true },
  { title: "You set it to Active", detail: "Shoppers can see it now, and not before.", you: true },
];

function Lane({ title, steps, start }: { title: string; steps: Step[]; start: number }) {
  return (
    <section className="flow-lane">
      <h3>{title}</h3>
      <ol start={start}>
        {steps.map((s) => (
          <li key={s.title} className={s.you ? "flow-step you" : "flow-step"}>
            <strong>{s.title}</strong>
            <span className="small">{s.detail}</span>
            <span className="flow-who small">{s.you ? "You" : "Automatic"}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function Support({ state }: { state: State }) {
  const live = state.publish_target === "live";
  return (
    <main className="page support-page">
      <h1>Support</h1>
      <p className="muted small">How Commerce OS works, for when you need a reminder.</p>

      <h2>How publishing works</h2>
      <p className="support-now small"><strong>Right now, Publish sends listings to {live ? "your live store, as Drafts" : "a local test store on this computer"}.</strong>{" "}
        {live ? "Shoppers don't see anything until you set it to Active in store admin." : "Your real store isn't changed. The steps below show how it works once the live store is connected."}</p>
      <div className="flow">
        <Lane title="In Commerce OS, on your computer" steps={HERE} start={1} />
        <div className="flow-arrow" aria-hidden="true">→</div>
        <Lane title="In your store" steps={STORE} start={5} />
      </div>

      <div className="support-grid">
        <section>
          <h3>What keeps a listing from going live early</h3>
          <ul className="small">
            <li>Only you can approve a listing.</li>
            <li>The worker is the only part of Commerce OS that can write to the store.</li>
            <li>Its login can't edit or delete products, or see customers and orders.</li>
            <li>The store hides Drafts from shoppers: on the shop, the art wall and direct links.</li>
          </ul>
        </section>
        <section>
          <h3>If something goes wrong</h3>
          <ul className="small">
            <li><strong>A draft isn't right:</strong> delete it in store admin. Its uploaded images may stay in storage, unused.</li>
            <li><strong>The connection drops while publishing:</strong> the listing moves to Needs a look. Commerce OS checks the store before you try again, so it won't add it twice.</li>
            <li><strong>You want everything to stop:</strong> press Stop all writing on the <a href="#/publish">Publish page</a>.</li>
          </ul>
        </section>
      </div>

      <InstallHelp />
    </main>
  );
}
