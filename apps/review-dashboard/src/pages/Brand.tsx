import { useEffect, useState } from "react";
import { api, BrandContext, State } from "../api";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export function Brand({ state, onChange }: { state: State; onChange: () => void }) {
  const [ctx, setCtx] = useState<BrandContext | null>(null);
  const [history, setHistory] = useState<Array<{ version: number; updated_at: string; updated_by: string }>>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const load = () => api.brand().then((b) => { setCtx(b.context); setHistory(b.history); setDirty(false); });
  useEffect(() => { load(); }, []);

  if (!ctx) return <main className="page"><p>No context yet. <a href="#/setup">Set it up</a>.</p></main>;
  const artist = ctx.site_kind === "artist";
  const up = (patch: Partial<BrandContext>) => { setCtx({ ...ctx, ...patch }); setDirty(true); };

  async function save() {
    setMsg(null);
    try { const saved = await api.saveBrand(ctx!); setMsg(`Saved as version ${saved.version}.`); await load(); onChange(); }
    catch (e) { setMsg(String((e as Error).message)); }
  }
  async function decide(id: string, status: string) {
    setMsg(null);
    try { await api.decide("example", id, status); await load(); onChange(); } catch (e) { setMsg(String((e as Error).message)); }
  }

  return (
    <main className="page narrow">
      <div className="row between page-head sticky-head">
        <h1>{artist ? "Artist context" : "Brand context"} <span className="muted">v{ctx.version}</span></h1>
        <div className="row">{msg && <span className="muted small">{msg}</span>}<button disabled={!dirty} onClick={save}>Save as new version</button></div>
      </div>
      <p className="muted">{artist ? "Artist site" : "Product site"} · every save is a new version, and each draft records the version it used. {state.brand && `Name in copy: ${ctx.identity.name}.`}</p>

      <fieldset><legend>Identity</legend>
        <label>Name <input value={ctx.identity.name} onChange={(e) => up({ identity: { ...ctx.identity, name: e.target.value } })} /></label>
        <label>Name usage <input value={ctx.identity.name_usage} onChange={(e) => up({ identity: { ...ctx.identity, name_usage: e.target.value } })} /></label>
        <label>Audience <input value={ctx.identity.audience || ""} onChange={(e) => up({ identity: { ...ctx.identity, audience: e.target.value } })} /></label>
      </fieldset>
      <fieldset><legend>{artist ? "Philosophy, in the artist's words" : "Brand story"}</legend>
        <textarea rows={8} value={ctx.philosophy} onChange={(e) => up({ philosophy: e.target.value })} />
      </fieldset>
      <fieldset><legend>{artist ? "Kinds of work" : "Product lines"}</legend>
        {ctx.categories.map((c, i) => (
          <div key={c.id} className="cat">
            <label title={c.id}>Name <input value={c.name} onChange={(e) => up({ categories: ctx.categories.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} /></label>
            <label>What it is <textarea rows={2} value={c.description} onChange={(e) => up({ categories: ctx.categories.map((x, j) => j === i ? { ...x, description: e.target.value } : x) })} /></label>
            <label>How to write about it <textarea rows={4} value={c.writing_approach} onChange={(e) => up({ categories: ctx.categories.map((x, j) => j === i ? { ...x, writing_approach: e.target.value } : x) })} /></label>
          </div>
        ))}
      </fieldset>
      <fieldset><legend>Voice</legend>
        <label>Tone <textarea rows={3} value={ctx.voice.tone} onChange={(e) => up({ voice: { ...ctx.voice, tone: e.target.value } })} /></label>
        <label>Always (one per line) <textarea rows={4} value={ctx.voice.do.join("\n")} onChange={(e) => up({ voice: { ...ctx.voice, do: lines(e.target.value) } })} /></label>
        <label>Never (one per line) <textarea rows={5} value={ctx.voice.avoid.join("\n")} onChange={(e) => up({ voice: { ...ctx.voice, avoid: lines(e.target.value) } })} /></label>
        <label>Style words accepted (one per line) <textarea rows={2} value={ctx.style_words.accept.join("\n")} onChange={(e) => up({ style_words: { ...ctx.style_words, accept: lines(e.target.value) } })} /></label>
        <label>Style words rejected (one per line) <textarea rows={2} value={ctx.style_words.reject.join("\n")} onChange={(e) => up({ style_words: { ...ctx.style_words, reject: lines(e.target.value) } })} /></label>
      </fieldset>
      <fieldset><legend>Phrases to watch</legend>
        <p className="muted small">Allowed, but limited to a share of the catalog. 0% means flag every use.</p>
        <table className="table"><tbody>
          {ctx.watch_phrases.map((w, i) => (
            <tr key={i}><td><input value={w.phrase} onChange={(e) => up({ watch_phrases: ctx.watch_phrases.map((x, j) => j === i ? { ...x, phrase: e.target.value } : x) })} /></td>
              <td><input type="number" min={0} max={100} value={Math.round(w.max_share * 100)} onChange={(e) => up({ watch_phrases: ctx.watch_phrases.map((x, j) => j === i ? { ...x, max_share: Math.min(1, Math.max(0, Number(e.target.value) / 100)) } : x) })} />%</td>
              <td><button className="link" onClick={() => up({ watch_phrases: ctx.watch_phrases.filter((_, j) => j !== i) })}>Remove</button></td></tr>
          ))}
        </tbody></table>
        <button className="secondary" onClick={() => up({ watch_phrases: [...ctx.watch_phrases, { phrase: "", max_share: 0.05, source: "owner" }] })}>Add phrase</button>
      </fieldset>

      <section className="panel"><h2>Confirmed meanings</h2>
        {ctx.meanings.length === 0 && <p className="muted">None yet. Add them from a listing's “What this piece means”.</p>}
        <ul>{ctx.meanings.map((m) => <li key={m.id}><span className="badge">{m.scope.kind}{m.scope.ref ? `: ${m.scope.ref}` : ""}</span> <strong>{m.subject}</strong>: {m.meaning}
          <button className="link" onClick={() => up({ meanings: ctx.meanings.filter((x) => x.id !== m.id) })}>Remove</button></li>)}</ul>
      </section>

      <section className="panel"><h2>Examples</h2>
        <p className="muted small">Only approved examples are shown to the writer, and only for voice.</p>
        {ctx.examples.map((e) => (
          <article key={e.id} className={`example ${e.status}`}>
            <div className="row between"><strong>{e.title}</strong><span className={`badge ${e.status === "approved" ? "ok" : e.status === "rejected" ? "bad" : "warn"}`}>{e.status}</span></div>
            <p>{e.short_description}</p><p className="small">{e.collector_description}</p><p className="muted small">Why: {e.why}</p>
            <div className="row">
              <button className="secondary" disabled={e.status === "approved" || dirty} onClick={() => decide(e.id, "approved")}>Approve</button>
              <button className="secondary" disabled={e.status === "rejected" || dirty} onClick={() => decide(e.id, "rejected")}>Reject</button>
            </div>
          </article>
        ))}
        {dirty && <p className="muted small">Save your changes before approving examples.</p>}
      </section>

      <section className="panel"><h2>Start over</h2>
        <p className="muted small">Voice setup asks the questions again and replaces the voice sections with a new version. <a href="#/setup">Open Voice setup</a></p>
      </section>

      <section className="panel"><h2>Versions</h2>
        <ul className="small"><li>v{ctx.version} (current) · {new Date(ctx.updated_at).toLocaleString()} · {ctx.updated_by.id}</li>
          {[...history].reverse().map((h) => <li key={h.version}>v{h.version} · {new Date(h.updated_at).toLocaleString()} · {h.updated_by}</li>)}</ul>
      </section>
    </main>
  );
}
