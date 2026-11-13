'use client';
/* Evidence upload (FR-EVD-001, FR-EVD-005): hash the file in the browser, ask for a slot with the SHA-256,
 * then send the bytes. The server hashes again and refuses a mismatch. Returns the evidence id. */
import { ApiError, type TenminaClient } from '@tenmina/api-client';
import { call } from '@tenmina/web-ui';

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

function csrf(): string {
  return document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1] ?? '';
}

export async function uploadEvidence(client: TenminaClient, file: File, subject: { subject_type: string; subject_id: string; role?: string; country?: string }): Promise<string> {
  const buf = await file.arrayBuffer();
  const type = file.type || (file.name.endsWith('.csv') ? 'text/csv' : 'application/octet-stream');
  const slot = await call<{ id: string }>(client, 'POST', '/v1/uploads', {
    subject_type: subject.subject_type, subject_id: subject.subject_id, role: subject.role ?? 'supporting',
    content_type: type, size_bytes: file.size, sha256: await sha256Hex(buf), original_name: file.name, country: subject.country ?? '',
  });
  const res = await fetch(`/v1/uploads/${slot.id}/content`, {
    method: 'PUT', credentials: 'include', body: buf,
    headers: { 'Content-Type': type, 'X-CSRFToken': csrf() },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError({ type: data.type ?? '', title: data.title ?? 'The file was not stored', status: res.status, detail: data.detail ?? '', code: data.code ?? 'error', blocking_reasons: data.blocking_reasons, errors: data.errors });
  }
  return data.id as string;
}
