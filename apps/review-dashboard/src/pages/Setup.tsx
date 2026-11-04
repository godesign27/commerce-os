import { useState } from "react";
import { api, State } from "../api";

interface Category { name: string; description: string; writing_approach: string }

// First run: the site-kind question decides the interview that follows.
export function Setup({ state, onDone }: { state: State; onDone: () => void }) {
  const [kind, setKind] = useState<"artist" | "product" | null>(state.site_kind);
  const [f, setF] = useState({ name: "", name_usage: "", audience: "", philosophy: "", tone: "", do: "", avoid: "", accept: "", reject: "", phrases: "" });
  const [cats, setCats] = useState<Category[]>([{ name: "", description: "", writing_approach: "" }]);
  const [error, setError] = useState<string | null>(null);
  const exists = !!state.brand;
  const artist = kind === "artist";
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function save() {
    setError(null);
    try {
      await api.setup({ ...f, site_kind: kind, categories: cats, replace: exists });
      location.hash = state.onboarding.complete ? "#/brand" : "#/start";
      onDone();
    } catch (e) { setError(String((e as Error).message)); }
  }

  return (
    <main className="page narrow">
      <h1>Set up {state.display_name}</h1>
      {exists && <p className="banner">{state.site_kind === "artist" ? "An artist" : "A product"} context (v{state.brand!.version}) already exists. Saving here replaces its voice sections with a new version; meanings, examples and lessons are not carried over. To adjust it, use the <a href="#/brand">{state.site_kind === "artist" ? "Artist context" : "Brand context"} page</a> instead.</p>}
      <fieldset>
        <legend>Is this an artist site or a product site?</legend>
        <label className="option"><input type="radio" checked={kind === "artist"} onChange={() => setKind("artist")} />
          <span><strong>Artist site</strong><br /><span className="muted small">One artist's own work. Copy speaks to what a piece means and the artist's intent.</span></span></label>
        <label className="option"><input type="radio" checked={kind === "product"} onChange={() => setKind("product")} />
          <span><strong>Product site</strong><br /><span className="muted small">A brand selling goods. Copy speaks to use, feel, fit and care.</span></span></label>
      </fieldset>
      {kind && (
        <>
          <fieldset>
            <legend>{artist ? "The artist" : "The brand"}</legend>
            <label>{artist ? "Artist name" : "Brand name"} <input value={f.name} onChange={set("name")} /></label>
            <label>How often may the name appear in copy? <input value={f.name_usage} onChange={set("name_usage")} placeholder="e.g. at most once in a long description" /></label>
            <label>Who buys? <input value={f.audience} onChange={set("audience")} /></label>
            <label>{artist ? "The idea behind the work, in the artist's own words" : "The brand story"}
              <textarea rows={6} value={f.philosophy} onChange={set("philosophy")} /></label>
          </fieldset>
          <fieldset>
            <legend>{artist ? "Kinds of work" : "Product lines"}</legend>
            {cats.map((c, i) => (
              <div key={i} className="cat">
                <label>Name <input value={c.name} onChange={(e) => setCats(cats.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} /></label>
                <label>What it is <input value={c.description} onChange={(e) => setCats(cats.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></label>
                <label>How to write about it <textarea rows={2} value={c.writing_approach} onChange={(e) => setCats(cats.map((x, j) => j === i ? { ...x, writing_approach: e.target.value } : x))} /></label>
              </div>
            ))}
            <button className="secondary" onClick={() => setCats([...cats, { name: "", description: "", writing_approach: "" }])}>Add another</button>
          </fieldset>
          <fieldset>
            <legend>Voice</legend>
            <label>Tone <input value={f.tone} onChange={set("tone")} /></label>
            <label>Always (one per line) <textarea rows={3} value={f.do} onChange={set("do")} /></label>
            <label>Never (one per line) <textarea rows={3} value={f.avoid} onChange={set("avoid")} /></label>
            <label>Style words {artist ? "the artist" : "you"} accept (one per line) <textarea rows={2} value={f.accept} onChange={set("accept")} /></label>
            <label>Style words to never use (one per line) <textarea rows={2} value={f.reject} onChange={set("reject")} /></label>
            <label>Phrases you're tired of (one per line) <textarea rows={3} value={f.phrases} onChange={set("phrases")} /></label>
          </fieldset>
          {error && <p className="error">{error}</p>}
          <button onClick={save}>Save {artist ? "artist" : "brand"} context</button>
        </>
      )}
    </main>
  );
}
