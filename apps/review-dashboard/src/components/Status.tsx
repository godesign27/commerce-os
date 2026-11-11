import { PieceStatus, StatusLabel } from "../api";

// One way to show a piece's status everywhere (B-074). The words come from packages/journey.py.
export function StatusBadge({ status }: { status: Pick<StatusLabel, "label" | "tone"> | null | undefined }) {
  if (!status) return null;
  return <span className={`status tone-${status.tone}`}>{status.label}</span>;
}

const STEP: Record<string, string> = {
  "review-photo": "Photo", "ready-to-draft": "Draft", "review-copy": "Copy", "add-details": "Details",
  "approve-for-store": "Store approval", "ready-to-publish": "Publish", published: "Published",
};
// Publishing sits between the last two steps; a problem sits where the piece last was.
// A published piece with a change waiting (B-085) is still at the last step: it's in the store.
const WHERE: Record<string, string> = { publishing: "published", "needs-look": "ready-to-publish", changed: "published",
  "ready-to-update": "published" };

export function Tracker({ status, pipeline }: { status: PieceStatus; pipeline: StatusLabel[] }) {
  const here = pipeline.findIndex((s) => s.id === (WHERE[status.id] || status.id));
  const finished = status.id === "published";
  return (
    <ol className="tracker" aria-label="Progress">
      {pipeline.map((s, i) => {
        const cls = i < here || (finished && i === here) ? "done" : i === here ? "here" : "";
        return <li key={s.id} className={cls} aria-current={i === here && !finished ? "step" : undefined}>{STEP[s.id]}</li>;
      })}
    </ol>
  );
}
