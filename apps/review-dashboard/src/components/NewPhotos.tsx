import { useEffect, useState } from "react";
import { api, Job, waitForJob } from "../api";

// Shown on every page when photos land in the inbox (B-068). Hiding it lasts until more arrive.
export function NewPhotos({ count, onDone }: { count: number; onDone: () => void }) {
  const [hidden, setHidden] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<{ added: number; duplicates: number; problems: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (count < hidden) setHidden(count); }, [count, hidden]);

  async function bringIn() {
    setError(null); setResult(null);
    try {
      const { job: id } = await api.scanInbox();
      const j = await waitForJob(id, setJob);
      if (j.error) setError(j.error);
      else setResult(j.results[0] as { added: number; duplicates: number; problems: number });
      onDone();
    } catch (e) { setError(String((e as Error).message)); }
  }

  if (result && !(count > 0 && count > hidden)) {
    const parts = [`${result.added} added`, result.duplicates ? `${result.duplicates} already here` : "", result.problems ? `${result.problems} with a problem` : ""].filter(Boolean);
    return (
      <div className="new-photos done" role="status">
        <span>{parts.join(", ")}.</span>
        <a href="#/photos" onClick={() => setResult(null)}>Review them →</a>
        <button className="link" onClick={() => setResult(null)}>Dismiss</button>
      </div>
    );
  }
  if (count <= hidden) return error ? <div className="new-photos" role="alert">{error}</div> : null;
  return (
    <div className="new-photos" role="status">
      <span className="dot" aria-hidden="true" />
      <strong>{count} new photo{count > 1 ? "s" : ""} in your inbox</strong>
      {error && <span className="small">{error}</span>}
      <button disabled={!!job?.running} onClick={bringIn}>{job?.running ? `Bringing in ${job.done}/${job.total}…` : "Bring them in"}</button>
      <button className="link" disabled={!!job?.running} onClick={() => setHidden(count)}>Later</button>
    </div>
  );
}
