import type { Problem } from '@tenmina/mobile';

/** One piece of assigned work from GET /v1/mobile/sync or /v1/mobile/inbox (FR-MOB-001). */
export interface Job {
  subject_type: string;
  subject_id: string;
  title: string;
  kind: string;
  country: string | null;
  status: string;
  address: string;
  point: { lat: number; lng: number } | null;
  radius_m: number | null;
  boundary: number[][];
  buffer_m: number | null;
  required_evidence: { key: string; label?: string; media?: 'photo' | 'video' | 'reading' | 'tick' | 'document' | 'text'; required?: boolean }[];
  checklist: { key: string; label?: string }[];
  plan_items: PlanItem[];
  previous_pass_at: string | null;
  project_key: string;
  accepts_submissions: boolean;
  state_reason: string;
  due_at: string | null;
  min_visit_minutes: number | null;
  details: Record<string, unknown>;
  updated_at: string | null;
  source: string;
}

export interface PlanItem {
  key: string;
  label: string;
  kind?: string;
  outcome?: string;
  /** "reading", "tick" or "photo" on a manual visit; a list on a care plan visit. */
  needs?: string | string[];
  photo_allowed?: boolean;
  reading_kind?: string;
}

export interface SyncResult {
  token: string;
  server_time: string;
  full: boolean;
  items: Job[];
  removed: { subject_type: string; subject_id: string }[];
  settings: Record<string, number>;
  devices: { id: string; status: string; platform: string; model: string }[];
}

/** A photo or video taken in this app's camera, signed when kept (02 8.4, RUL-08). */
export interface Capture {
  id: string;
  subjectType: string;
  subjectId: string;
  requirementKey: string;
  kind: 'photo' | 'video';
  uri: string;
  mediaType: string;
  size: number;
  sha256: string;
  takenAt: string;
  lat?: number;
  lng?: number;
  accuracyM?: number;
  distanceM?: number;
  note?: string;
  signed: { manifest: Record<string, unknown>; signature: string; signature_alg: string };
  state: 'waiting' | 'registered' | 'uploaded' | 'stored' | 'rejected';
  manifestId?: string;
  evidenceId?: string;
  flags?: { kind: string; detail?: unknown }[];
}

export type OpKind =
  | 'evidence'
  | 'submission'
  | 'inspection'
  | 'checkin'
  | 'checkout'
  | 'visit_item'
  | 'concern'
  | 'errand_start'
  | 'errand_receipt'
  | 'errand_done'
  | 'errand_result'
  | 'errand_handover'
  | 'expense';

/** Something waiting to reach Tenmina, kept on the phone until the server confirms it (FR-MOB-005). */
export interface Op {
  id: string;
  kind: OpKind;
  label: string;
  subjectType: string;
  subjectId: string;
  createdAt: string;
  state: 'waiting' | 'sending' | 'sent' | 'failed';
  sentAt?: string;
  /** The API call. Evidence ids are filled from captures at send time. */
  method: 'POST' | 'PUT';
  path: string;
  body?: Record<string, unknown>;
  /** Capture ids this op needs stored first, and where their evidence ids go in the body. */
  needs?: { captureId: string; at: string }[];
  captureId?: string;
  problem?: Problem;
  attempts: number;
  result?: unknown;
}
