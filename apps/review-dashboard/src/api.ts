// Thin client for the local API (services/local_api/server.py). Every write carries X-Commerce-OS.

export type Severity = "blocking" | "warning" | "note";
export interface Issue { id: string; severity: Severity; target: string; question: string; resolver?: string }
export interface Copy {
  title: string; short_description: string; collector_description: string;
  store_tags: string[]; search_keywords: string[];
}
export type Field = keyof Copy;
export interface Check { severity: Severity; field: Field; check: string; message: string }
export interface ItemRow {
  id: string; source: string; kind: string; image?: string; framed?: string; crop_decision?: string | null;
  has_art: boolean; drafted: boolean; revision: number | null; title: string | null; approved: boolean;
  edited: boolean; blocking: number; supplied: number; warnings: number; category: string | null;
  storefront: StorefrontState | null;
  published: PublishState | null;
  status: PieceStatus; thumb: string | null;
}
// One status per piece, from packages/journey.py (B-074). Every page shows this and works nothing out for itself.
export type StatusId = "review-photo" | "ready-to-draft" | "review-copy" | "add-details" | "approve-for-store"
  | "ready-to-publish" | "publishing" | "published" | "needs-look" | "rejected";
export type StatusTone = "todo" | "wait" | "done" | "bad" | "off";
export interface StatusLabel { id: StatusId; label: string; tone: StatusTone }
export interface PieceStatus extends StatusLabel {
  next: string; detail: string; blockers: Array<{ target: string; question: string }>;
}
// A listing against the storefront (B-064): blocked, ready to approve, approved, or approved but changed since.
export type StorefrontState = "blocked" | "ready" | "approved" | "out_of_date";
export interface HistoryEvent { at: string | null; event: string; label: string; by: string }
export interface PreviewRow { column: string; label: string; value: unknown; display: unknown; before: unknown; evidence: string }
// Publishing (B-070). The dashboard only asks; the worker writes, and only reports success after reading it back.
export type PublishState = "QUEUED" | "WRITING" | "SUCCEEDED" | "FAILED" | "OUTCOME_UNKNOWN";
export interface KillSwitch { on: boolean; forced: boolean; at: string | null; by: string | null }
export interface WorkerStatus { running: boolean; ok: boolean; reason: string | null }
export interface PublishDoc {
  target: string; live: boolean; state: PublishState | null; kill_switch: KillSwitch; worker: WorkerStatus;
  product_id: string | null; receipt_id: string | null; published_at: string | null;
  reasons: string[]; finding: "mismatch" | "not_found" | null; fields: string[]; checking: boolean;
}
// The publish page (B-071): every drafted listing, sorted by what it needs next.
export interface QueueRow {
  id: string; source: string; title: string | null; image: string | null;
  price: { amount_minor: number; currency: string } | null; sold_as: string | null; size: string | null;
  status: PieceStatus; state: PublishState | null; change_set_hash: string | null; approved_at: string | null; next: string[];
  product_id: string | null; receipt_id: string | null; published_at: string | null;
  reasons: string[]; finding: "mismatch" | "not_found" | null; fields: string[]; checking: boolean;
}
export interface PublishQueue {
  available: boolean; reason?: string; target: string; live: boolean; display_name: string; kill_switch: KillSwitch; worker: WorkerStatus;
  ready: QueueRow[]; working: QueueRow[]; problems: QueueRow[]; waiting: QueueRow[]; published: QueueRow[]; not_drafted: number;
}
// A product in the store that may already be this piece (B-065). Shown for the owner to answer; never a source of facts.
export interface MatchCandidate {
  product_id: string; name: string | null; slug: string | null; status: string | null; level: "likely" | "possible";
  matching: string[]; conflicting: string[]; medium: string | null; dimensions: string | null;
  answer: "same" | "different" | null;
}
export interface StorefrontPreview {
  available: boolean; reason?: string; storefront?: string; display_name?: string; environment?: string;
  change_set?: { change_set_id: string; change_set_hash: string; requested_status: string; mapping_version: number;
                 canonical_revision: number; asset_manifest_hash: string; not_touched: string[] };
  rows?: PreviewRow[]; images?: Array<{ kind: "framed" | "room"; image: string }>; blockers?: Issue[]; notes?: string[];
  dry_run?: { would_publish: boolean; issues: Array<{ code: string; message: string }> }; approvable?: boolean;
  approval?: { state: "none" | "current" | "out_of_date"; changes: string[];
               approval: { approval_id: string; approved_at: string; change_set_hash: string; requested_status: string } | null };
  catalog?: { read_at: string | null; products: number; candidates: MatchCandidate[] };
  publish?: PublishDoc;
  history: HistoryEvent[];
}
export interface Job {
  id: string; label: string; running: boolean; done: number; total: number; error: string | null;
  cost_usd: number; results: Array<Record<string, unknown>>;
}
export interface State {
  statuses: StatusLabel[];
  storefront: string; display_name: string; site_kind: "artist" | "product" | null;
  brand: { version: number; name: string; proposed_lessons: number } | null;
  items: ItemRow[]; key_configured: boolean; jobs: Job[]; onboarding: Steps; publish_target: "local" | "live";
}
// First run (B-068). Nothing here ever holds a credential.
export interface Steps { steps: Array<{ id: string; label: string; done: boolean }>; complete: boolean; next: string | null }
export interface OnboardingDoc extends Steps {
  storefront: string;
  store: { display_name: string | null; site_kind: "artist" | "product" | null; provider: string | null; currency: string | null };
  providers: Array<{ id: string; label: string }>;
  login: { env_key: string | null; saved: boolean; sql: string; example: string; where: string };
  check: { read_at: string; products: number; categories: number; tags: number } | null;
  choices: {
    categories: Array<{ ref: string; name: string }>; tags: Array<{ ref: string; name: string }>; tier_types: string[];
    product_types: Array<{ id: string; label: string }>;
    chosen: { categories: string[]; tags: string[]; tier_types: string[];
              product_types: Record<string, { category: string | null; alternative: string | null }> };
  } | null;
}
export interface InboxStatus { new: number; waiting: number; folder: string }
export interface HomeDoc {
  onboarding: Steps; inbox: InboxStatus; statuses: StatusLabel[]; pipeline: StatusLabel[];
  pieces: Array<{ id: string; title: string | null; source: string; thumb: string | null; status: PieceStatus }>;
  next: { headline: string; detail: string; label: string; href: string } | null;
  store: { connected: boolean; display_name: string | null; site_kind: string | null; provider: string | null;
           products: number | null; read_at: string | null; writes_enabled: boolean };
  photos: { total: number; to_review: number; ready: number; rejected: number };
  listings: { drafted: number; copy_approved: number; blocked: number; ready: number; approved: number; out_of_date: number; published: number; publish_problems: number; to_publish: number };
  publishing: { target: string; kill_switch: KillSwitch; worker: WorkerStatus };
  rooms: { total: number; ready: number; need_attention: number };
  learning: { approvals: number; proposed_lessons: number };
}
export interface Meaning {
  id: string; scope: { kind: "artwork" | "series" | "catalog"; ref: string | null };
  subject: string; meaning: string; recorded_at: string;
}
export interface Draft {
  revision: number; drafted_at: string; model: string; cost_usd: number | null; prompt?: string;
  brand_context?: string; proposed: Copy; effective: Copy;
  title_options: Array<{ title: string; angle: string; rationale: string }>; title_reason?: string;
  category?: string; moment?: { text: string; basis: "confirmed" | "proposed" };
  observations: string[]; interpretations: Array<{ statement: string; basis: string; meaning_id: string | null }>;
  ask_artist: string[]; self_review: Record<string, number>; proposed_new_tags: string[];
  subject?: string; colors: string[]; rotate?: number; signature?: string | null;
  issues: Issue[]; policy_violations: string[];
  inputs: { note?: string; facts?: Record<string, string>; meanings?: string[]; catalog_size?: number; edit_pairs?: boolean };
}
export interface Listing {
  facts?: { edition?: string; medium?: string; dimensions?: string; price?: string; sold_as?: string }; series?: string; note?: string;
  edits?: Partial<Copy>; chosen_title?: string;
  approved?: { at: string; by: string; revision: number; copy: Copy };
}
export interface Detail {
  item: { id: string; source: string; kind: string; framed?: string };
  image?: string; listing: Listing; revisions: number[]; meanings: Meaning[];
  categories: Array<{ id: string; name: string }>; draft: Draft | null; size_from_name: string | null;
  tier_types: string[]; status: PieceStatus; pipeline: StatusLabel[];
}
export interface Lesson { id: string; text: string; status: "proposed" | "approved" | "rejected"; source: string; evidence: string[]; created_at: string }
export interface Example { id: string; status: "proposed" | "approved" | "rejected"; category: string; title: string; short_description: string; collector_description: string; why: string }
export interface BrandContext {
  contract: "brand-context"; contract_version: 1; storefront_id: string; site_kind: "artist" | "product";
  version: number; updated_at: string; updated_by: { kind: string; id: string };
  identity: { name: string; name_usage: string; audience?: string }; philosophy: string;
  categories: Array<{ id: string; name: string; description: string; writing_approach: string }>;
  voice: { tone: string; do: string[]; avoid: string[] }; style_words: { accept: string[]; reject: string[] };
  meanings: Meaning[]; watch_phrases: Array<{ phrase: string; max_share: number; source?: string }>;
  examples: Example[]; lessons: Lesson[];
  length: { short_words: { min: number; max: number }; collector_words: { min: number; max: number }; short_chars_max: number };
}
export type Stage = "to-review" | "not-applied" | "ready" | "drafted" | "approved" | "rejected";
export interface PhotoEvent { event: string; label: string; at: string | null }
export interface Photo {
  id: string; source: string; kind: "photo" | "artwork"; image?: string; photo?: string; framed?: string;
  stage: Stage; decision: "accept" | "reject" | "fix" | null; rotate: number; note: string;
  crop_flagged: boolean; crop_reasons: string[]; error?: string | null;
  events: PhotoEvent[]; updated_at: string | null; status: PieceStatus | null; title: string | null;
}
export type Pt = [number, number];
export interface PhotoDetail extends Photo {
  photo_size?: [number, number]; photo_preview_size?: [number, number]; cropped?: string; original?: string;
  art_size?: [number, number];
  detected: { corners: Pt[] | null; method: string | null; ok: boolean | null; reasons: string[] };
  corners: Pt[] | null; applied: { corners: Pt[] | null; rotate: number };
  prev: string | null; next: string | null; listing_title: string | null;
  dimensions: string | null; facts: { edition?: string; medium?: string; dimensions?: string; price?: string; sold_as?: string }; series: string;
  room: RoomView | null; room_options: RoomOption[]; size_from_name: string | null; tier_types: string[];
}
export interface RoomOption { id: string; name: string; status: RoomStatus; image: string; preview: string | null }
export interface RoomView { room: string; name: string; auto: boolean; unavailable: string | null; image: string | null; stale: boolean; guessed: boolean; fitted: boolean; overflows: boolean; frame_cm: [number, number] | null; fits_elsewhere: string[] }
export type RoomStatus = "ready" | "needs-licence" | "needs-wall" | "off";
export interface Room {
  id: string; name: string; file: string; image: string; preview: string | null; size: [number, number];
  source_file: string; licence: string | null; credit: string; url: string; note: string;
  wall: Pt[] | null; wall_width_cm: number | null; wall_height_cm: number | null; light: number; shadow: number;
  enabled: boolean; status: RoomStatus; added_at: string; updated_at: string; preview_piece?: string;
  named_by?: "file" | "owner" | "suggestion";
  suggested?: { name: string | null; wall: Pt[] | null; wall_width_cm: number | null; reference: string;
                confidence: "low" | "medium" | "high"; model: string; cost_usd: number; at: string } | null;
}
// What a room still needs, in words: "Needs its width" when only the width is missing (B-063).
export function roomLabel(r: Pick<Room, "status" | "enabled" | "wall" | "wall_width_cm" | "suggested">, statuses: RoomsDoc["statuses"]): string {
  const st: RoomStatus = r.enabled ? r.status : "off";
  if (st === "needs-wall") return r.wall && !r.wall_width_cm ? "Needs its width" : r.suggested?.wall ? "Check its wall" : "Wall not marked";
  return statuses.find((s) => s.id === st)?.label || st;
}
export interface RoomsDoc {
  rooms: Room[]; licences: Array<{ id: string; label: string }>; statuses: Array<{ id: RoomStatus; label: string }>;
  inbox: string; pieces: Array<{ id: string; source: string }>;
}
export type RoomChanges = Partial<Pick<Room, "name" | "wall" | "wall_width_cm" | "light" | "shadow" | "enabled" | "licence" | "credit" | "url" | "note">>;
export interface PhotosDoc { stages: Array<{ id: Stage; label: string }>; statuses: StatusLabel[]; photos: Photo[]; pending: number; review_page: string; intake: IntakeStatus }
// The local inbox folder (B-066): what's waiting, and what the last look found.
export interface IntakeStatus {
  folder: string; waiting: number; new: number;
  last: { at: string; added: Array<{ name: string; source_name: string }>; duplicates: Array<{ name: string; same_as: string }>;
          problems: Array<{ name: string; reason: string }>; left: number } | null;
}
export interface EditRecord {
  id: string; at: string; item: string; field: string; event: string; changed: boolean;
  proposed: string; final: string; diff: { similarity: number; removed: string[]; added: string[]; length_change: number };
}
export interface LearningDoc {
  stats: { approvals: number; by_field: Record<string, { records: number; accepted_unchanged: number; similarity: number; similarity_latest_10: number }> };
  edits: EditRecord[]; repeated_removals: Array<{ phrase: string; items: string[] }>;
  lessons: Lesson[]; examples: Example[]; changed: number;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-Commerce-OS": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || `${res.status}`);
  return data as T;
}

export interface NameSize { id: string; source: string; size: string; image?: string }   // a size read from the file name
export const api = {
  state: () => call<State>("GET", "/api/state"),
  item: (id: string) => call<Detail>("GET", `/api/items/${id}`),
  nameSizes: () => call<{ pieces: NameSize[] }>("GET", "/api/sizes/from-names"),
  saveNameSizes: (ids: string[]) =>
    call<{ saved: Array<{ id: string; size: string }>; skipped: Array<{ id: string; reason: string }> }>("POST", "/api/sizes/from-names", { ids }),
  saveListing: (id: string, body: Partial<Listing>) => call<Listing>("PUT", `/api/items/${id}/listing`, body),
  saveCopy: (id: string, fields: Partial<Record<Field, string | string[] | null>>) =>
    call<{ item: string; copy: Copy; saved: Field[]; checks: Check[] }>("PUT", `/api/items/${id}/copy`, { fields }),
  redraft: (id: string) => call<{ job: string }>("POST", `/api/items/${id}/draft`),
  approve: (id: string) => call<{ edits_recorded: number }>("POST", `/api/items/${id}/approve`),
  unlock: (id: string) => call<Listing>("POST", `/api/items/${id}/unlock`),
  storefront: (id: string) => call<StorefrontPreview>("GET", `/api/items/${id}/storefront`),
  // Gate 3: approve the exact change set shown, by its hash; refused if the listing changed since.
  approveStorefront: (id: string, change_set_hash: string, status: string) =>
    call<StorefrontPreview>("POST", `/api/items/${id}/storefront/approve`, { change_set_hash, status }),
  addMeaning: (id: string, body: { scope: string; subject: string; meaning: string; series?: string }) =>
    call<BrandContext>("POST", `/api/items/${id}/meaning`, body),
  draftPending: (limit: number) => call<{ job: string }>("POST", "/api/draft-pending", { limit }),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  brand: () => call<{ context: BrandContext | null; history: Array<{ version: number; updated_at: string; updated_by: string }>; storefront: Record<string, unknown> }>("GET", "/api/brand"),
  saveBrand: (ctx: BrandContext) => call<BrandContext>("PUT", "/api/brand", ctx),
  setup: (body: Record<string, unknown>) => call<BrandContext>("POST", "/api/setup", body),
  decide: (kind: "lesson" | "example", id: string, status: string, text?: string) =>
    call<BrandContext>("POST", `/api/brand/${kind}s/${id}`, { status, text }),
  learning: () => call<LearningDoc>("GET", "/api/learning"),
  distil: () => call<{ job: string }>("POST", "/api/learning/distil"),
  photos: () => call<PhotosDoc>("GET", "/api/photos"),
  photo: (id: string) => call<PhotoDetail>("GET", `/api/photos/${id}`),
  decidePhoto: (id: string, body: { decision?: "accept" | "reject" | null; rotate?: number; note?: string; corners?: Pt[] | null }) =>
    call<Photo>("PUT", `/api/photos/${id}`, body),
  applyPhotos: () => call<{ job: string }>("POST", "/api/photos/apply"),
  publish: (id: string, change_set_hash: string) => call<StorefrontPreview>("POST", `/api/items/${id}/publish`, { change_set_hash }),
  publishQueue: () => call<PublishQueue>("GET", "/api/publishing/queue"),
  publishMany: (items: Array<{ id: string; change_set_hash: string }>) =>
    call<{ results: Array<{ id: string; ok: boolean; error?: string }>; queue: PublishQueue }>("POST", "/api/publishing/publish", { items }),
  publishRecheck: (id: string) => call<StorefrontPreview>("POST", `/api/items/${id}/publish/recheck`),
  killSwitch: (on: boolean) => call<KillSwitch>("PUT", "/api/publishing/kill-switch", { on }),
  home: () => call<HomeDoc>("GET", "/api/home"),
  inbox: () => call<InboxStatus>("GET", "/api/inbox"),
  onboarding: () => call<OnboardingDoc>("GET", "/api/onboarding"),
  onboardingStore: (body: object) => call<OnboardingDoc>("PUT", "/api/onboarding/store", body),
  onboardingLogin: (url: string) => call<OnboardingDoc>("POST", "/api/onboarding/login", { url }),
  onboardingCheck: () => call<OnboardingDoc>("POST", "/api/onboarding/check"),
  onboardingMapping: (body: object) => call<OnboardingDoc>("PUT", "/api/onboarding/mapping", body),
  onboardingKey: (key: string) => call<OnboardingDoc>("POST", "/api/onboarding/key", { key }),
  scanInbox: () => call<{ job: string }>("POST", "/api/intake/scan"),
  refreshCatalog: () => call<{ job: string }>("POST", "/api/catalog/refresh"),
  answerMatch: (id: string, product_id: string, answer: "same" | "different" | null) =>
    call<StorefrontPreview>("PUT", `/api/items/${id}/catalog-match`, { product_id, answer }),
  // {} hangs the piece in its room; {room} chooses that room first; {room: null} goes back to the automatic pick.
  photoRoom: (id: string, body: { room?: string | null } = {}) => call<PhotoDetail>("POST", `/api/photos/${id}/room`, body),
  rooms: () => call<RoomsDoc>("GET", "/api/rooms"),
  room: (id: string) => call<Room>("GET", `/api/rooms/${id}`),
  saveRoom: (id: string, body: RoomChanges) => call<Room>("PUT", `/api/rooms/${id}`, body),
  scanRooms: () => call<{ added: string[]; rooms: Room[] }>("POST", "/api/rooms/scan"),
  previewRoom: (id: string, piece?: string) => call<Room>("POST", `/api/rooms/${id}/preview`, { piece }),
  renderRooms: () => call<{ job: string }>("POST", "/api/rooms/render"),
  suggestRooms: (rooms: string[]) => call<{ job: string }>("POST", "/api/rooms/suggest", { rooms }),
  suggestRoom: (id: string) => call<Room>("POST", `/api/rooms/${id}/suggest`),
  uploadRoom: async (file: File, meta: { name?: string; licence?: string; credit?: string }) => {
    // The photo itself is the body (not JSON); what's known about it rides in the query.
    const q = new URLSearchParams({ filename: file.name, ...Object.fromEntries(Object.entries(meta).filter(([, v]) => v)) });
    const res = await fetch(`/api/rooms/upload?${q}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Commerce-OS": "1" }, body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data as { error?: string }).error || `${res.status}`);
    return data as Room & { added: boolean };
  },
};

export async function waitForJob(id: string, onTick?: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api.job(id);
    onTick?.(j);
    if (!j.running) return j;
    await new Promise((r) => setTimeout(r, 1500));
  }
}
