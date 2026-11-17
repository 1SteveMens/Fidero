import { useCallback, useState } from 'react';
import { Platform, View } from 'react-native';
import { router } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import * as Crypto from 'expo-crypto';
import { File as FsFile } from 'expo-file-system';
import { space } from '@tenmina/tokens';
import { Button, ListRow, Panel, T } from '@tenmina/ui';
import { ProblemBox, day, itemsOf, newUuid, toProblem, useApi, useGet, type MobileApi, type Problem } from '@tenmina/mobile';
import { typeFromName } from '../lib';

/**
 * Files in the client app: pick a document or a photo, hash it, send it through
 * an evidence upload slot, and open any file inside the app (FR-EVD-001,
 * FR-EVD-003). The client may choose files or photos from the library; Tenmina
 * Field stays camera only (RUL-08).
 */

/** A file the person picked, ready to hash and send. */
export interface Picked {
  uri: string;
  name: string;
  type: string;
  size: number;
  /** On the web the picker hands over the browser File. */
  blob?: Blob;
}

/** What POST /v1/uploads/{id}/content answers: the stored evidence. */
export interface StoredEvidence {
  id: string;
  sha256: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
}

/** A row of GET /v1/evidence?subject_type=&subject_id=. */
export interface EvidenceRow {
  id: string;
  original_name: string;
  content_type: string;
  description: string;
  uploaded_by_name: string;
  created_at: string;
  provenance: string;
}

export interface Subject {
  type: string;
  id: string;
  role?: string;
  description?: string;
  country?: string;
}

/** Types the evidence store takes (evidence.services.ALLOWED_UPLOAD_TYPES). */
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'application/pdf'];

/** Open the files app or the photo library. Returns null when the person cancels. */
export async function pickFile(source: 'files' | 'photos'): Promise<Picked | null> {
  if (source === 'photos') {
    if (Platform.OS !== 'web') {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) throw new Error('Allow Tenmina to see your photos in Settings, or choose a file instead.');
    }
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.8, exif: false, allowsMultipleSelection: false });
    if (r.canceled || !r.assets.length) return null;
    const a = r.assets[0];
    const name = a.fileName || `photo-${Date.now()}.jpg`;
    const type = a.mimeType || typeFromName(name);
    return { uri: a.uri, name, type: type === 'application/octet-stream' ? 'image/jpeg' : type, size: a.fileSize ?? a.file?.size ?? 0, blob: a.file };
  }
  const r = await DocumentPicker.getDocumentAsync({ type: ACCEPTED, copyToCacheDirectory: true, multiple: false });
  if (r.canceled || !r.assets.length) return null;
  const a = r.assets[0];
  return { uri: a.uri, name: a.name, type: a.mimeType || typeFromName(a.name), size: a.size ?? a.file?.size ?? 0, blob: a.file };
}

function hex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** The file's SHA-256 and size, read on the phone before it is sent; the API checks both (FR-EVD-001). */
async function fingerprint(p: Picked): Promise<{ sha256: string; size: number }> {
  if (Platform.OS === 'web') {
    const blob = p.blob ?? (await (await fetch(p.uri)).blob());
    const buf = await blob.arrayBuffer();
    return { sha256: hex(await crypto.subtle.digest('SHA-256', buf)), size: buf.byteLength };
  }
  const f = new FsFile(p.uri);
  const size = f.size || p.size;
  const withDigest = f as unknown as { digest?: (a: 'SHA-256') => Promise<string> };
  if (typeof withDigest.digest === 'function') {
    try {
      return { sha256: (await withDigest.digest('SHA-256')).toLowerCase(), size };
    } catch {
      // An older native module: hash the bytes instead.
    }
  }
  const bytes = await f.bytes();
  return { sha256: hex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes)), size: bytes.byteLength };
}

/** Ask for an upload slot with the SHA-256, then send the bytes to it. Returns the stored evidence. */
export async function uploadEvidence(api: MobileApi, p: Picked, subject: Subject): Promise<StoredEvidence> {
  const { sha256, size } = await fingerprint(p);
  const slot = await api.post<{ id: string }>(
    '/v1/uploads',
    {
      subject_type: subject.type,
      subject_id: subject.id,
      role: subject.role ?? 'supporting',
      content_type: p.type,
      size_bytes: size,
      sha256,
      original_name: p.name,
      description: subject.description ?? '',
      country: subject.country ?? '',
    },
    { idempotencyKey: `slot-${newUuid()}` },
  );
  const form = new FormData();
  if (Platform.OS === 'web') {
    form.append('file', p.blob ?? (await (await fetch(p.uri)).blob()), p.name);
  } else {
    // React Native sends a local file by its address in a multipart form.
    form.append('file', { uri: p.uri, name: p.name, type: p.type } as unknown as Blob);
  }
  return api.request<StoredEvidence>('PUT', `/v1/uploads/${slot.id}/content`, { form });
}

/**
 * Pick, hash and upload in one step, with a busy flag and the API's problem
 * for ProblemBox. `then` runs with the stored evidence (for example to hand it
 * to a document request).
 */
export function useUpload() {
  const api = useApi();
  const [busy, setBusy] = useState<'files' | 'photos' | null>(null);
  const [problem, setProblem] = useState<Problem>();
  const upload = useCallback(
    async (source: 'files' | 'photos', subject: Subject, then?: (ev: StoredEvidence) => Promise<unknown> | unknown): Promise<StoredEvidence | undefined> => {
      setProblem(undefined);
      let picked: Picked | null;
      try {
        picked = await pickFile(source);
      } catch (e) {
        setProblem(toProblem(e));
        return undefined;
      }
      if (!picked) return undefined;
      setBusy(source);
      try {
        const ev = await uploadEvidence(api, picked, subject);
        if (then) await then(ev);
        return ev;
      } catch (e) {
        setProblem(toProblem(e));
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [api],
  );
  return { upload, busy, problem, clear: () => setProblem(undefined) };
}

/** Two buttons: a document from Files, or a photo from the library. */
export function AddFile({
  subject,
  onDone,
  then,
  label = 'Add a file',
  variant = 'dark',
}: {
  subject: Subject;
  onDone?: (ev: StoredEvidence) => void;
  then?: (ev: StoredEvidence) => Promise<unknown> | unknown;
  label?: string;
  variant?: 'primary' | 'dark';
}) {
  const up = useUpload();
  const go = async (source: 'files' | 'photos') => {
    const ev = await up.upload(source, subject, then);
    if (ev) onDone?.(ev);
  };
  return (
    <View style={{ gap: space[2] }} accessibilityLabel={label}>
      <T v="footnote" style={{ fontWeight: '600' }}>{label}</T>
      <View style={{ flexDirection: 'row', gap: space[2] }}>
        <View style={{ flex: 1 }}>
          <Button title="Files" icon="folder-open-outline" variant={variant} loading={up.busy === 'files'} disabled={!!up.busy} onPress={() => void go('files')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button title="Photos" icon="images-outline" variant="dark" loading={up.busy === 'photos'} disabled={!!up.busy} onPress={() => void go('photos')} />
        </View>
      </View>
      <ProblemBox problem={up.problem} />
    </View>
  );
}

/** Open a stored file inside the app: images full screen, PDFs in the reader. */
export function openFile(id: string, name?: string, type?: string) {
  router.push({ pathname: '/file/[id]', params: { id, name: name ?? '', type: type ?? '' } });
}

export function iconForType(type: string) {
  if (type.startsWith('image/')) return 'image-outline' as const;
  if (type === 'application/pdf') return 'document-text-outline' as const;
  if (type.startsWith('video/')) return 'videocam-outline' as const;
  return 'document-outline' as const;
}

/** One stored file as a row that opens it. */
export function FileRow({ id, name, type, detail, last }: { id: string; name: string; type: string; detail?: string; last?: boolean }) {
  return <ListRow icon={iconForType(type)} iconTone="surface" title={name || 'File'} detail={detail} onPress={() => openFile(id, name, type)} last={last} />;
}

/** Every file on a subject the person may see (GET /v1/evidence), newest first, each opening in the app. */
export function EvidenceFiles({ subjectType, subjectId, empty = 'No files yet.', tick = 0 }: { subjectType: string; subjectId: string; empty?: string; tick?: number }) {
  const list = useGet<{ items: EvidenceRow[] } | EvidenceRow[]>('/v1/evidence', { subject_type: subjectType, subject_id: subjectId, tick });
  const rows = itemsOf(list.data).filter((e) => !e.content_type.includes('json'));
  if (list.problem) return <ProblemBox problem={list.problem} onRetry={list.reload} />;
  if (!list.data) return null;
  if (!rows.length) return <T v="footnote" muted>{empty}</T>;
  return (
    <Panel style={{ paddingVertical: space[1], gap: 0 }}>
      {rows.map((e, i) => (
        <FileRow key={e.id} id={e.id} name={e.original_name || e.description} type={e.content_type} detail={`${e.uploaded_by_name || 'Tenmina'} · ${day(e.created_at)}`} last={i === rows.length - 1} />
      ))}
    </Panel>
  );
}
