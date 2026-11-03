import { useMemo, useState } from "react";
import { api, State, waitForJob, Job } from "../api";
import { NameSizes } from "../components/NameSizes";

type Filter = "all" | "drafted" | "to-draft" | "approved" | "edited" | "blocking" | "store-ready" | "store-approved" | "store-out-of-date";
const FILTER_LABELS: Partial<Record<Filter, string>> = {
  approved: "copy approved", "store-ready": "ready for the store", "store-approved": "approved for the store",
  "store-out-of-date": "store approval out of date",
};

export function Listings({ state, onChange }: { state: State; onChange: () => void }) {
  const [filter, setFilter] = useState<Filter>("drafted");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = useMemo(() => state.items.filter((i) => i.has_art && i.crop_decision !== "reject"), [state.items]);
  const shown = items.filter((i) => ({
    all: true, drafted: i.drafted, "to-draft": !i.drafted, approved: i.approved, edited: i.edited && !i.approved,
    blocking: i.blocking > 0, "store-ready": i.storefront === "ready", "store-approved": i.storefront === "approved",
    "store-out-of-date": i.storefront === "out_of_date",
  })[filter]);
  const toDraft = items.filter((i) => !i.drafted).length;

  async function draft(n: number) {
    setError(null);
    try {
      const { job: id } = await api.draftPending(n);
      await waitForJob(id, setJob);
      onChange();
    } catch (e) { setError(String((e as Error).message)); }
  }

  const counts: Record<Filter, number> = {
    all: items.length, drafted: items.filter((i) => i.drafted).length, "to-draft": toDraft,
    approved: items.filter((i) => i.approved).length, edited: items.filter((i) => i.edited && !i.approved).length,
    blocking: items.filter((i) => i.blocking > 0).length,
    "store-ready": items.filter((i) => i.storefront === "ready").length,
    "store-approved": items.filter((i) => i.storefront === "approved").length,
    "store-out-of-date": items.filter((i) => i.storefront === "out_of_date").length,
  };
  return (
    <main className="page">
      <div className="row between">
        <h1>Listings</h1>
        <div className="row">
          {job?.running && <span className="muted">{job.label}: {job.done}/{job.total}…</span>}
          {job && !job.running && <span className="muted">Done · ${job.cost_usd.toFixed(2)}{job.error ? ` · ${job.error}` : ""}</span>}
          <NameSizes onSaved={onChange} />
          <button disabled={!state.key_configured || !toDraft || !!job?.running} onClick={() => draft(5)}>
            Draft next {Math.min(5, toDraft)}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="filters" role="group" aria-label="Filter">
        {(Object.keys(counts) as Filter[]).map((f) => (
          <button key={f} className="chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {FILTER_LABELS[f] || f.replace("-", " ")} <span>{counts[f]}</span>
          </button>
        ))}
      </div>
      <ul className="grid">
        {shown.map((i) => (
          <li key={i.id}>
            <a className={`card ${i.approved ? "is-approved" : ""}`} href={`#/listings/${i.id}`}>
              {i.image && <img src={`/${i.image}`} alt="" loading="lazy" />}
              <div className="card-body">
                <strong>{i.title || <span className="muted">Not drafted</span>}</strong>
                <span className="muted small">{i.source}</span>
                <span className="badges">
                  {i.approved && <span className="badge ok">Approved</span>}
                  {i.storefront === "approved" && <span className="badge ok">Store ✓</span>}
                  {i.storefront === "ready" && <span className="badge">Ready for the store</span>}
                  {i.storefront === "out_of_date" && <span className="badge bad">Store approval out of date</span>}
                  {i.edited && !i.approved && <span className="badge">Edited</span>}
                  {i.drafted && <span className="badge">r{i.revision}</span>}
                  {i.blocking > 0 && <span className="badge bad">{i.blocking} to supply</span>}
                  {i.supplied > 0 && <span className="badge" title="Supplied since this draft: redraft to use it in the copy">
                    {i.supplied} supplied · redraft</span>}
                  {i.warnings > 0 && <span className="badge warn">{i.warnings} check{i.warnings === 1 ? "" : "s"}</span>}
                </span>
              </div>
            </a>
          </li>
        ))}
      </ul>
      {!shown.length && <p className="muted">Nothing here.</p>}
    </main>
  );
}
