'use client';
/* File helpers for role pages: hash in the browser, upload to an evidence slot, multipart posts.
   Every upload is tamper-evident: the API checks the SHA-256 we send against the bytes (FR-EVD-001). */
import { ApiError } from '@tenmina/api-client';

function readCookie(name: string): string {
  if (typeof document === 'undefined') return '';
  return document.cookie.split('; ').find((c) => c.startsWith(name + '='))?.split('=')[1] ?? '';
}

function uuid(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Date.now()) + Math.random();
}

export async function sha256Hex(data: Blob | ArrayBuffer): Promise<string> {
  const buf = data instanceof Blob ? await data.arrayBuffer() : data;
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function toBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

async function problemFrom(res: Response): Promise<ApiError> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let e: any = {};
  try { e = await res.json(); } catch { /* not JSON */ }
  return new ApiError({
    type: e.type ?? '', title: e.title ?? res.statusText, status: res.status, detail: e.detail ?? '',
    code: e.code ?? 'error', blocking_reasons: e.blocking_reasons, errors: e.errors,
  });
}

/** Send any request with the session cookie, CSRF and an Idempotency-Key. Returns JSON or null. */
export async function send<T = unknown>(method: string, path: string, body?: BodyInit | null, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(path, {
    method,
    body: body ?? undefined,
    credentials: 'include',
    headers: { 'X-CSRFToken': readCookie('csrftoken'), 'Idempotency-Key': uuid(), ...headers },
  });
  if (!res.ok) throw await problemFrom(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

/** POST multipart form data (a file field named `file`, plus other fields). */
export function postForm<T = unknown>(path: string, fields: Record<string, string | Blob | undefined | null>): Promise<T> {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null && v !== '') fd.append(k, v);
  return send<T>('POST', path, fd);
}

export type Evidence = { id: string; sha256: string; status?: string };

/** Ask for an upload slot with the file's SHA-256, then PUT the bytes. Returns the stored evidence. */
export async function uploadEvidence(file: File, subject: { type: string; id: string; role?: string; country?: string; description?: string }): Promise<Evidence> {
  const sha = await sha256Hex(file);
  const slot = await send<{ id: string }>('POST', '/v1/uploads', JSON.stringify({
    subject_type: subject.type, subject_id: subject.id, role: subject.role || 'supporting',
    content_type: file.type || 'application/octet-stream', size_bytes: file.size, sha256: sha,
    original_name: file.name, description: subject.description || '', country: subject.country || '',
  }), { 'Content-Type': 'application/json' });
  return send<Evidence>('PUT', `/v1/uploads/${slot.id}/content`, file, { 'Content-Type': 'application/octet-stream' });
}

/** Open a short-lived signed link for a piece of evidence in a new tab. */
export async function openEvidence(id: string) {
  const link = await send<{ url: string }>('GET', `/v1/evidence/${id}/link`);
  window.open(link.url, '_blank', 'noopener');
}

/** Download a file the API streams (for example a statement PDF). */
export async function download(path: string, name: string) {
  const res = await fetch(path, { credentials: 'include' });
  if (!res.ok) throw await problemFrom(res);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
