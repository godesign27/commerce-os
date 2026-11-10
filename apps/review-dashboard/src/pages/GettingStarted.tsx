import { useCallback, useEffect, useMemo, useState } from "react";
import { api, OnboardingDoc, State } from "../api";
import { CopyBlock } from "../components/CopyBlock";
import { InstallHelp, StepHelp } from "../components/SetupHelp";

// First run (B-068). Each step's status comes from what's actually set up, so you can stop and come back.
// A generated password stays in this page until it's part of the login you enter below it.
function newPassword(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(30));
  return Array.from(bytes, (b) => "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"[b % 57]).join("");
}

function StoreStep({ doc, act }: { doc: OnboardingDoc; act: Act }) {
  const [f, setF] = useState({ display_name: doc.store.display_name || "", site_kind: doc.store.site_kind || "",
    provider: doc.store.provider || "", currency: doc.store.currency || "USD" });
  return (
    <form onSubmit={(e) => { e.preventDefault(); act(() => api.onboardingStore(f)); }}>
      <label>Store name <input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
      <fieldset>
        <legend>What kind of store is it?</legend>
        <label className="option"><input type="radio" name="kind" checked={f.site_kind === "artist"} onChange={() => setF({ ...f, site_kind: "artist" })} />
          <span><strong>Artist site</strong><br /><span className="muted small">One artist's own work.</span></span></label>
        <label className="option"><input type="radio" name="kind" checked={f.site_kind === "product"} onChange={() => setF({ ...f, site_kind: "product" })} />
          <span><strong>Product site</strong><br /><span className="muted small">A brand selling goods.</span></span></label>
      </fieldset>
      <label>Where is its database?
        <select value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })}>
          <option value="">Choose…</option>
          {doc.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select></label>
      <label>Currency <input value={f.currency} maxLength={3} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} /></label>
      <p className="muted small">Commerce OS can't change anything in your store: writes stay off.</p>
      <button type="submit">Save store</button>
    </form>
  );
}

function LoginStep({ doc, act }: { doc: OnboardingDoc; act: Act }) {
  const [password, setPassword] = useState(newPassword);
  const [url, setUrl] = useState("");
  const sql = doc.login.sql.replace("<password>", password);
  return (
    <div>
      <p className="small">Commerce OS needs a login that can only read your products, categories and tags. If you already
        have one, skip to the last part.</p>
      <h3>1. Create the login</h3>
      <p className="muted small">{doc.login.where}</p>
      <CopyBlock text={sql} label="Script that creates the read-only login" />
      <p className="muted small">The password in this script was made on this page and hasn't been sent anywhere.{" "}
        <button className="link" onClick={() => setPassword(newPassword())}>Make a new one</button></p>
      <h3>2. Enter the login</h3>
      <p className="muted small">It looks like this, with your password:</p>
      <CopyBlock text={doc.login.example} label="What the login looks like" />
      <form onSubmit={(e) => { e.preventDefault(); act(() => api.onboardingLogin(url), () => setUrl("")); }}>
        <label>Login <input type="password" autoComplete="off" spellCheck={false} value={url} onChange={(e) => setUrl(e.target.value)} /></label>
        <p className="muted small">It's checked first and only saved if it can't change data or see customer tables. It goes in
          {" "}<code>.env</code> on this computer, readable only by you, and is never shown again.</p>
        <button type="submit" disabled={!url.trim()}>Check and save</button>
      </form>
    </div>
  );
}

function CheckStep({ act }: { act: Act }) {
  return (
    <div>
      <p className="small">Read your store's structure and catalog. This changes nothing in the store.</p>
      <button onClick={() => act(() => api.onboardingCheck())}>Check the store</button>
    </div>
  );
}

function MappingStep({ doc, act }: { doc: OnboardingDoc; act: Act }) {
  const c = doc.choices!;
  const [cats, setCats] = useState<string[]>(c.chosen.categories);
  const [tags, setTags] = useState<string[]>(c.chosen.tags);
  const [tiers, setTiers] = useState<string[]>(c.chosen.tier_types);
  const [typed, setTyped] = useState("");
  const [types, setTypes] = useState(c.chosen.product_types);
  const [ladders, setLadders] = useState<string[]>(c.chosen.tier_ladders || []);
  const toggle = (list: string[], set: (x: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const inUse = c.categories.filter((x) => cats.includes(x.ref));
  const tierOptions = useMemo(() => Array.from(new Set([...c.tier_types, ...tiers])), [c.tier_types, tiers]);
  return (
    <form onSubmit={(e) => { e.preventDefault(); act(() => api.onboardingMapping({ categories: cats, tags, tier_types: tiers, product_types: types, tier_ladders: ladders })); }}>
      <p className="small">These are your store's own lists. Choose what Commerce OS may use.</p>
      <fieldset><legend>Categories</legend>
        {c.categories.map((x) => <label className="inline" key={x.ref}><input type="checkbox" checked={cats.includes(x.ref)} onChange={() => toggle(cats, setCats, x.ref)} /> {x.name}</label>)}
        {!c.categories.length && <p className="muted small">The store has no categories.</p>}
      </fieldset>
      <fieldset><legend>Tags</legend>
        {c.tags.map((x) => <label className="inline" key={x.ref}><input type="checkbox" checked={tags.includes(x.ref)} onChange={() => toggle(tags, setTags, x.ref)} /> {x.name}</label>)}
        {!c.tags.length && <p className="muted small">The store has no tags.</p>}
      </fieldset>
      <fieldset><legend>How pieces are sold</legend>
        {tierOptions.map((t) => <label className="inline" key={t}><input type="checkbox" checked={tiers.includes(t)} onChange={() => toggle(tiers, setTiers, t)} /> {t}</label>)}
        {!c.tier_types.length && (
          <div className="row">
            <label>The store has no products to read these from. Add one <input value={typed} onChange={(e) => setTyped(e.target.value)} /></label>
            <button type="button" className="secondary" disabled={!typed.trim()} onClick={() => { setTiers([...tiers, typed.trim()]); setTyped(""); }}>Add</button>
          </div>)}
      </fieldset>
      {c.tier_ladders.length > 0 && (
        <fieldset><legend>Usual pricing tiers</legend>
          <p className="muted small">Your store usually sells an original with these prints. Tick a size to add its tiers to
            every new original that size. You'll see them in each listing's preview before you approve it.</p>
          {c.tier_ladders.map((l) => (
            <div key={l.size} className="ladder">
              <label className="inline"><input type="checkbox" checked={ladders.includes(l.size)} onChange={() => toggle(ladders, setLadders, l.size)} />
                {" "}<strong>{l.label} originals</strong></label>
              <p className="ladder-basis muted small">Seen on {l.based_on} of your {l.of} originals this size</p>
              <ul className="ladder-tiers small">
                {l.tiers.map((t, i) => <li key={i}>{t.type}, {t.size}: {t.price.toLocaleString("en-US", { style: "currency", currency: "USD" })}
                  {t.description ? ` (${t.description})` : ""}</li>)}
              </ul>
            </div>))}
        </fieldset>)}
      <fieldset><legend>Where things go</legend>
        {c.product_types.map((t) => (
          <div key={t.id} className="row">
            <label>{t.label} goes in
              <select value={types[t.id]?.category || ""} onChange={(e) => setTypes({ ...types, [t.id]: { category: e.target.value || null, alternative: types[t.id]?.alternative || null } })}>
                <option value="">Not sold here</option>
                {inUse.map((x) => <option key={x.ref} value={x.ref}>{x.name}</option>)}
              </select></label>
            {t.id === "artwork" && (
              <label>Prints go in
                <select value={types[t.id]?.alternative || ""} onChange={(e) => setTypes({ ...types, [t.id]: { category: types[t.id]?.category || null, alternative: e.target.value || null } })}>
                  <option value="">The same category</option>
                  {inUse.map((x) => <option key={x.ref} value={x.ref}>{x.name}</option>)}
                </select></label>)}
          </div>
        ))}
      </fieldset>
      <button type="submit">Save choices</button>
    </form>
  );
}

function KeyStep({ act }: { act: Act }) {
  const [key, setKey] = useState("");
  return (
    <form onSubmit={(e) => { e.preventDefault(); act(() => api.onboardingKey(key), () => setKey("")); }}>
      <p className="small">Claude writes the listing drafts. Create a key at console.anthropic.com; each draft costs a little.</p>
      <label>API key <input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} /></label>
      <p className="muted small">It's checked, then saved in <code>.env</code> on this computer, and never shown again.</p>
      <button type="submit" disabled={!key.trim()}>Check and save</button>
    </form>
  );
}

type Act = (fn: () => Promise<OnboardingDoc>, after?: () => void) => void;

export function GettingStarted({ onChange }: { state: State; onChange: () => void }) {
  const [doc, setDoc] = useState<OnboardingDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api.onboarding().then(setDoc).catch((e) => setError(String(e.message))); }, []);
  const act: Act = useCallback(async (fn, after) => {
    setBusy(true); setError(null);
    try { setDoc(await fn()); setOpen(null); after?.(); onChange(); }
    catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  }, [onChange]);
  if (!doc) return <main className="page narrow">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</main>;
  const current = open ?? doc.next;
  const currentStep = doc.steps.find((s) => s.id === current);

  const body = (id: string) => {
    if (id === "store") return <StoreStep doc={doc} act={act} />;
    if (id === "login") return doc.store.provider ? <LoginStep doc={doc} act={act} /> : <p className="muted small">Set up your store first.</p>;
    if (id === "check") return doc.login.saved ? <CheckStep act={act} /> : <p className="muted small">Save the read-only login first.</p>;
    if (id === "mapping") return doc.choices ? <MappingStep doc={doc} act={act} /> : <p className="muted small">Check the store first.</p>;
    if (id === "key") return <KeyStep act={act} />;
    if (id === "voice") return <p className="small">Tell Commerce OS how to write about your work. <a href="#/setup">Answer the questions →</a></p>;
    return <p className="small">Put one photo per piece in <code>inbox</code> in the Commerce OS folder, then <a href="#/photos">look for new photos →</a>.
      From there: accept each photo, draft its copy, add its facts and approve it. Nothing reaches your real store: publishing only goes to a local test store for now.</p>;
  };
  const summary = (id: string) => {
    if (id === "store" && doc.store.display_name) return doc.store.display_name;
    if (id === "login" && doc.login.saved) return "Saved";
    if (id === "check" && doc.check) return `${doc.check.products} products, ${doc.check.categories} categories, ${doc.check.tags} tags`;
    return "";
  };

  return (
    <main className="page gs-page">
      <h1>Getting started</h1>
      <p className="muted small">{doc.complete ? "Everything's set up. You can change any step here." : "Connect your store and set up how Commerce OS writes. You can stop and come back: this page remembers."}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="gs-layout">
        <div className="gs-main">
          <ol className="gs-steps" aria-busy={busy}>
            {doc.steps.map((s, n) => (
              <li key={s.id} className={`gs-step ${s.done ? "done" : ""} ${current === s.id ? "current" : ""}`}>
                <button className="gs-head" aria-expanded={current === s.id} onClick={() => setOpen(current === s.id ? "" : s.id)}>
                  <span className="gs-mark" aria-hidden="true">{s.done ? "✓" : n + 1}</span>
                  <span className="gs-label">{s.label}</span>
                  <span className="muted small">{s.done ? summary(s.id) || "Done" : ""}</span>
                </button>
                {current === s.id && (
                  <div className="gs-body">
                    <details className="gs-help-inline"><summary>Help with this step</summary><StepHelp id={s.id} doc={doc} /></details>
                    {body(s.id)}
                  </div>)}
              </li>
            ))}
          </ol>
          {doc.complete && <p><a href="#/home">Go to your start page →</a></p>}
        </div>
        <aside className="gs-side" aria-label="Help">
          {currentStep && (
            <section className="gs-help-side">
              <h2>Help: {currentStep.label}</h2>
              <StepHelp id={currentStep.id} doc={doc} />
            </section>)}
          <InstallHelp />
        </aside>
      </div>
    </main>
  );
}
