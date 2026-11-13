import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';
import { useNetInfo } from '@react-native-community/netinfo';
import { ApiError, APP_VERSION, OfflineError, newUuid, platformName, toProblem, useSession, type MobileApi, type Problem } from '@tenmina/mobile';
import { canonical, sha256Hex, sign, signingKey, forgetSigningKey } from './signing';
import { dropFile, loadState, saveState, webBlobs } from './persist';
import type { Capture, Job, Op, OpKind, SyncResult } from './types';

/** An errand assigned to this agent (GET /v1/mobile/errands). */
export interface FieldErrand {
  id: string;
  reference: string;
  status: string;
  name: string;
  agency_payee: { name?: string } | string | null;
  due_on: string | null;
  steps: {
    id: string;
    seq: number;
    key: string;
    description: string;
    official_fee: { amount: string; currency: string };
    status: string;
    plain: string;
    has_acknowledgement: boolean;
    has_receipt: boolean;
    release_instruction_id: string | null;
    needs_documents: string[];
    started_at: string | null;
    paid_at: string | null;
    done_at: string | null;
  }[];
  documents: { key: string; label: string; status: string }[];
  result_uploaded_at: string | null;
  result_note: string;
  handover: unknown;
}

interface Saved {
  personId: string | null;
  device: { id: string; status: string; registeredAt: string; alg: string } | null;
  syncToken: string | null;
  lastServerTime: string | null;
  offsetMs: number;
  lastSyncAt: string | null;
  jobs: Job[];
  errands: FieldErrand[];
  captures: Capture[];
  ops: Op[];
  previousSha: string | null;
  /** Local progress per job key, so a visit or checklist survives a restart. */
  progress: Record<string, Record<string, unknown>>;
  noSignal: boolean;
}

const EMPTY: Saved = {
  personId: null,
  device: null,
  syncToken: null,
  lastServerTime: null,
  offsetMs: 0,
  lastSyncAt: null,
  jobs: [],
  errands: [],
  captures: [],
  ops: [],
  previousSha: null,
  progress: {},
  noSignal: false,
};

export const jobKey = (subjectType: string, subjectId: string) => `${subjectType}:${subjectId}`;

interface Position {
  lat: number;
  lng: number;
  accuracyM?: number;
  mock?: boolean;
}

interface Field {
  online: boolean;
  noSignal: boolean;
  setNoSignal: (v: boolean) => void;
  device: Saved['device'];
  registering: boolean;
  registerProblem?: Problem;
  registerDevice: () => Promise<void>;
  jobs: Job[];
  errands: FieldErrand[];
  lastSyncAt: string | null;
  syncProblem?: Problem;
  syncNow: () => Promise<void>;
  captures: Capture[];
  ops: Op[];
  capturesFor: (subjectType: string, subjectId: string, key?: string) => Capture[];
  keepCapture: (c: Omit<Capture, 'signed' | 'state'>) => Promise<Capture>;
  dropCapture: (id: string) => void;
  queue: (o: { kind: OpKind; label: string; subjectType: string; subjectId: string; method?: 'POST' | 'PUT'; path: string; body?: Record<string, unknown>; needs?: Op['needs']; id?: string }) => Op;
  signedCheck: (kind: 'checkin' | 'checkout', subjectType: string, subjectId: string, pos: Position) => Promise<Op>;
  retry: (opId: string) => void;
  removeOp: (opId: string) => void;
  progress: (key: string) => Record<string, unknown>;
  setProgress: (key: string, patch: Record<string, unknown>) => void;
  reset: () => Promise<void>;
}

const FieldContext = createContext<Field | null>(null);

function setPath(obj: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split('.');
  let cur: Record<string, unknown> | unknown[] = obj;
  parts.forEach((p, i) => {
    const k: string | number = /^\d+$/.test(p) ? Number(p) : p;
    if (i === parts.length - 1) (cur as Record<string | number, unknown>)[k] = value;
    else cur = (cur as Record<string | number, unknown>)[k] as Record<string, unknown>;
  });
}

/** Problems worth trying again later; anything else stops the item until the person looks at it. */
function retryable(p: Problem) {
  return p.status === 0 || p.status >= 500 || p.status === 429 || p.status === 401 || p.status === 408;
}

function deviceModel(): string {
  const c = Platform.constants as { Model?: string; model?: string; systemName?: string } | undefined;
  return c?.Model ?? c?.model ?? (Platform.OS === 'ios' ? 'iPhone' : Platform.OS === 'web' ? 'Web preview' : 'Android phone');
}

class Wait extends Error {}

/**
 * Tenmina Field's offline-first store (02 section 8.5, FR-MOB-005): this phone's
 * registration and key, the jobs from the last sync, every capture with its
 * signed manifest, and the queue of calls waiting for signal. The queue is sent
 * in order, each call with its own client-generated id, so a retry never doubles.
 */
export function FieldProvider({ children }: { children: ReactNode }) {
  const { api, me, status } = useSession();
  const [saved, setSaved] = useState<Saved>(() => loadState(EMPTY));
  const ref = useRef(saved);
  ref.current = saved;
  const net = useNetInfo();
  const online = !saved.noSignal && net.isConnected !== false && net.isInternetReachable !== false;
  const [registering, setRegistering] = useState(false);
  const [registerProblem, setRegisterProblem] = useState<Problem>();
  const [syncProblem, setSyncProblem] = useState<Problem>();
  const pumping = useRef(false);

  const update = useCallback((fn: (s: Saved) => Saved) => {
    setSaved((s) => {
      const n = fn(s);
      ref.current = n;
      return n;
    });
  }, []);

  useEffect(() => saveState(saved), [saved]);

  // A different person on this phone starts clean: their own key, jobs and queue.
  useEffect(() => {
    if (status !== 'signedIn' || !me) return;
    if (ref.current.personId && ref.current.personId !== me.id) {
      void forgetSigningKey();
      update(() => ({ ...EMPTY, personId: me.id }));
    } else if (!ref.current.personId) {
      update((s) => ({ ...s, personId: me.id }));
    }
  }, [status, me, update]);

  /** Register this phone's key (8.2): a challenge from the server, the key, and the attestation. */
  const registerDevice = useCallback(async () => {
    setRegistering(true);
    setRegisterProblem(undefined);
    try {
      const key = await signingKey(true);
      if (!key) throw new Error('No key');
      const { challenge } = await api.post<{ challenge: string }>('/v1/mobile/devices/challenge');
      const platform = platformName();
      const keySha = sha256Hex(Uint8Array.from(atobBytes(key.publicKey)));
      // The store build sends the real App Attest object or the Android key attestation with
      // Play Integrity. This build sends the development server's fake, marked as a stand-in.
      const attestation =
        platform === 'ios'
          ? { challenge, build: 'store', environment: 'production', counter: 0, key_id: `dev-${key.publicKey.slice(-12)}`, key_sha256: keySha, stand_in: 'software key, development build' }
          : { challenge, build: 'store', key_security: key.security, device_integrity: 'MEETS_DEVICE_INTEGRITY', app_recognized: true, stand_in: 'software key, development build' };
      const d = await api.post<{ id: string; status: string; key_alg: string; registered_at: string }>('/v1/mobile/devices', {
        challenge,
        platform,
        app_id: 'com.tenmina.field',
        public_key: key.publicKey,
        attestation,
        model: deviceModel(),
        os_version: `${Platform.OS} ${String(Platform.Version ?? '')}`.trim(),
        app_version: APP_VERSION,
      });
      update((s) => ({ ...s, device: { id: d.id, status: d.status, registeredAt: d.registered_at, alg: d.key_alg } }));
    } catch (e) {
      setRegisterProblem(toProblem(e));
    } finally {
      setRegistering(false);
    }
  }, [api, update]);

  /** Pull assigned work: everything the first time, then what changed since the token (8.5 step 1). */
  const pull = useCallback(async () => {
    const s = ref.current;
    const r = await api.get<SyncResult>('/v1/mobile/sync', { since: s.syncToken ?? undefined, device_id: s.device?.id });
    const offset = Date.parse(r.server_time) - Date.now();
    let errands = s.errands;
    try {
      const e = await api.get<{ items: FieldErrand[] }>('/v1/mobile/errands');
      errands = e.items ?? [];
    } catch {
      // not an errand agent
    }
    update((cur) => {
      let jobs = r.full ? [] : [...cur.jobs];
      const gone = new Set(r.removed.map((x) => jobKey(x.subject_type, x.subject_id)));
      jobs = jobs.filter((j) => !gone.has(jobKey(j.subject_type, j.subject_id)));
      for (const it of r.items) {
        const k = jobKey(it.subject_type, it.subject_id);
        const i = jobs.findIndex((j) => jobKey(j.subject_type, j.subject_id) === k);
        if (i >= 0) jobs[i] = it;
        else jobs.push(it);
      }
      return { ...cur, jobs, errands, syncToken: r.token, lastServerTime: r.server_time, offsetMs: offset, lastSyncAt: new Date().toISOString() };
    });
  }, [api, update]);

  /** Send one queued item. Evidence goes in three steps: the signed manifest, the bytes, then complete (8.5 steps 2 to 4). */
  const runOp = useCallback(
    async (op: Op) => {
      if (op.kind === 'evidence') {
        let c = ref.current.captures.find((x) => x.id === op.captureId);
        if (!c) throw Object.assign(new Error('gone'), { problem: { type: 'about:blank', title: 'Capture missing', status: 410, code: 'capture-missing', detail: 'This capture is no longer on the phone.' } });
        const patch = (p: Partial<Capture>) => {
          update((s) => ({ ...s, captures: s.captures.map((x) => (x.id === c!.id ? { ...x, ...p } : x)) }));
          c = { ...c!, ...p };
        };
        if (!c.manifestId) {
          const r = await api.post<{ id: string; status: Capture['state']; evidence_id: string }>('/v1/mobile/evidence', c.signed);
          patch({ manifestId: r.id, evidenceId: r.evidence_id, state: r.status });
        }
        if (c.state === 'registered' || c.state === 'uploaded') {
          const form = new FormData();
          const name = `${c.id}.${c.kind === 'video' ? 'mp4' : 'jpg'}`;
          if (Platform.OS === 'web') {
            const blob = webBlobs.get(c.id);
            if (!blob) throw new ApiError({ type: 'about:blank', title: 'Capture missing', status: 410, code: 'capture-missing', detail: 'The web preview lost this capture when the page reloaded. Take it again.' });
            form.append('file', blob, name);
          } else {
            form.append('file', { uri: c.uri, name, type: c.mediaType } as unknown as Blob);
          }
          await api.request('PUT', `/v1/mobile/evidence/${c.manifestId}/content`, { form });
          patch({ state: 'uploaded' });
          const done = await api.post<{ status: Capture['state']; evidence_id: string; flags: { kind: string; detail?: unknown }[] }>(`/v1/mobile/evidence/${c.manifestId}/complete`, {});
          patch({ state: done.status, evidenceId: done.evidence_id, flags: done.flags });
          if (done.status === 'stored') {
            dropFile(c.uri);
            webBlobs.delete(c.id);
          }
        }
        return c;
      }
      const body = JSON.parse(JSON.stringify(op.body ?? {})) as Record<string, unknown>;
      for (const n of op.needs ?? []) {
        const c = ref.current.captures.find((x) => x.id === n.captureId);
        if (!c || c.state === 'rejected') {
          throw new ApiError({ type: 'about:blank', title: 'A photo was not accepted', status: 422, code: 'capture-rejected', detail: 'One of the photos for this item was not accepted. Take it again, then send this again.' });
        }
        if (c.state !== 'stored' || !c.evidenceId) throw new Wait();
        setPath(body, n.at, c.evidenceId);
      }
      return api.request(op.method, op.path, { body, idempotencyKey: op.id });
    },
    [api, update],
  );

  /** Send everything waiting, in order. Stops at the first sign of no signal and tries again later. */
  const pump = useCallback(async () => {
    if (pumping.current) return;
    pumping.current = true;
    try {
      for (;;) {
        const op = ref.current.ops.find((o) => o.state === 'waiting');
        if (!op) break;
        update((s) => ({ ...s, ops: s.ops.map((o) => (o.id === op.id ? { ...o, state: 'sending', attempts: o.attempts + 1 } : o)) }));
        try {
          const result = await runOp(op);
          update((s) => ({ ...s, ops: s.ops.map((o) => (o.id === op.id ? { ...o, state: 'sent', sentAt: new Date().toISOString(), problem: undefined, result: op.kind === 'evidence' ? undefined : result } : o)) }));
        } catch (e) {
          if (e instanceof Wait) {
            update((s) => ({ ...s, ops: s.ops.map((o) => (o.id === op.id ? { ...o, state: 'waiting' } : o)) }));
            break;
          }
          const p = (e as { problem?: Problem }).problem ?? toProblem(e);
          const again = e instanceof OfflineError || retryable(p);
          update((s) => ({ ...s, ops: s.ops.map((o) => (o.id === op.id ? { ...o, state: again ? 'waiting' : 'failed', problem: p } : o)) }));
          if (op.kind === 'evidence' && !again) {
            update((s) => ({ ...s, captures: s.captures.map((c) => (c.id === op.captureId ? { ...c, state: 'rejected' } : c)) }));
          }
          if (again) break;
        }
      }
    } finally {
      pumping.current = false;
    }
  }, [runOp, update]);

  const syncNow = useCallback(async () => {
    if (status !== 'signedIn') return;
    try {
      await pump();
      await pull();
      setSyncProblem(undefined);
    } catch (e) {
      setSyncProblem(toProblem(e));
    }
  }, [pump, pull, status]);

  // Send and refresh when signal comes back, when the queue grows, and every minute.
  const waiting = saved.ops.filter((o) => o.state === 'waiting').length;
  useEffect(() => {
    if (!online || status !== 'signedIn' || !saved.device) return;
    void syncNow();
    const t = setInterval(() => void syncNow(), 60_000);
    return () => clearInterval(t);
  }, [online, status, saved.device, waiting, syncNow]);

  const queue = useCallback<Field['queue']>(
    (o) => {
      const id = o.id ?? newUuid();
      // A body with an empty client_submission_id takes the op's own id: one id for the queue, the retry and the server.
      const body = o.body && 'client_submission_id' in o.body && !o.body.client_submission_id ? { ...o.body, client_submission_id: id } : o.body;
      const op: Op = { id, kind: o.kind, label: o.label, subjectType: o.subjectType, subjectId: o.subjectId, createdAt: new Date().toISOString(), state: 'waiting', method: o.method ?? 'POST', path: o.path, body, needs: o.needs, attempts: 0 };
      update((s) => ({ ...s, ops: [...s.ops, op] }));
      return op;
    },
    [update],
  );

  /** Seal a kept capture: sign its manifest now, chained to the last item from this phone (8.4). */
  const keepCapture = useCallback<Field['keepCapture']>(
    async (c) => {
      const key = await signingKey(true);
      const s = ref.current;
      if (!key || !s.device) throw new Error('This phone is not registered yet.');
      const manifest: Record<string, unknown> = {
        schema: 'tenmina.evidence.v1',
        client_item_id: c.id,
        device_id: s.device.id,
        subject: { type: c.subjectType, id: c.subjectId, ...(c.requirementKey ? { requirement_key: c.requirementKey } : {}) },
        media: { type: c.mediaType, size_bytes: c.size, sha256: c.sha256 },
        captured_at_device: c.takenAt,
        camera: { lens: 'back', model: deviceModel(), platform: platformName(), app_version: APP_VERSION, ...(Platform.OS === 'web' ? { emulator: true } : {}) },
        ...(s.lastServerTime ? { last_server_time_sync: { server: s.lastServerTime, offset_ms: Math.round(s.offsetMs) } } : {}),
        ...(c.lat !== undefined && c.lng !== undefined ? { location: { lat: c.lat, lng: c.lng, accuracy_m: c.accuracyM ?? 9999, provider: 'gps', mock: false } } : {}),
        ...(s.previousSha ? { previous_item_sha256: s.previousSha } : {}),
      };
      const full: Capture = { ...c, signed: sign(key, manifest), state: 'waiting' };
      update((cur) => ({
        ...cur,
        previousSha: c.sha256,
        captures: [...cur.captures, full],
        ops: [...cur.ops, { id: newUuid(), kind: 'evidence', label: c.note ? `${c.requirementKey || c.kind}: ${c.note}` : `${c.kind === 'video' ? 'Video' : 'Photo'}: ${c.requirementKey || 'evidence'}`, subjectType: c.subjectType, subjectId: c.subjectId, createdAt: new Date().toISOString(), state: 'waiting', method: 'POST', path: '/v1/mobile/evidence', captureId: c.id, attempts: 0 }],
      }));
      return full;
    },
    [update],
  );

  /** A signed check-in or check-out at the registered address (FR-MOB-012), queued like evidence. */
  const signedCheck = useCallback<Field['signedCheck']>(
    async (kind, subjectType, subjectId, pos) => {
      const key = await signingKey(true);
      const s = ref.current;
      if (!key || !s.device) throw new Error('This phone is not registered yet.');
      const manifest: Record<string, unknown> = {
        schema: 'tenmina.checkin.v1',
        kind,
        client_item_id: newUuid(),
        device_id: s.device.id,
        subject: { type: subjectType, id: subjectId },
        captured_at_device: new Date().toISOString(),
        location: { lat: pos.lat, lng: pos.lng, accuracy_m: pos.accuracyM ?? 9999, provider: 'gps', mock: !!pos.mock },
        camera: { model: deviceModel(), platform: platformName(), app_version: APP_VERSION },
        ...(s.lastServerTime ? { last_server_time_sync: { server: s.lastServerTime, offset_ms: Math.round(s.offsetMs) } } : {}),
        ...(s.previousSha ? { previous_item_sha256: s.previousSha } : {}),
      };
      const signed = sign(key, manifest);
      const op: Op = {
        id: newUuid(),
        kind,
        label: kind === 'checkin' ? 'Check-in at the address' : 'Check-out',
        subjectType,
        subjectId,
        createdAt: new Date().toISOString(),
        state: 'waiting',
        method: 'POST',
        path: kind === 'checkin' ? '/v1/mobile/check-ins' : '/v1/mobile/check-outs',
        body: signed as unknown as Record<string, unknown>,
        attempts: 0,
      };
      update((cur) => ({ ...cur, previousSha: sha256Hex(canonical(manifest)), ops: [...cur.ops, op] }));
      return op;
    },
    [update],
  );

  const value = useMemo<Field>(
    () => ({
      online,
      noSignal: saved.noSignal,
      setNoSignal: (v) => update((s) => ({ ...s, noSignal: v })),
      device: saved.device,
      registering,
      registerProblem,
      registerDevice,
      jobs: saved.jobs,
      errands: saved.errands,
      lastSyncAt: saved.lastSyncAt,
      syncProblem,
      syncNow,
      captures: saved.captures,
      ops: saved.ops,
      capturesFor: (st, sid, key) => saved.captures.filter((c) => c.subjectType === st && c.subjectId === sid && (key === undefined || c.requirementKey === key) && c.state !== 'rejected'),
      keepCapture,
      dropCapture: (id) =>
        update((s) => {
          const c = s.captures.find((x) => x.id === id);
          if (!c || c.manifestId) return s; // already sent: kept as evidence
          if (c.uri) dropFile(c.uri);
          return { ...s, captures: s.captures.filter((x) => x.id !== id), ops: s.ops.filter((o) => o.captureId !== id) };
        }),
      queue,
      signedCheck,
      retry: (id) => update((s) => ({ ...s, ops: s.ops.map((o) => (o.id === id ? { ...o, state: 'waiting', problem: undefined } : o)) })),
      removeOp: (id) => update((s) => ({ ...s, ops: s.ops.filter((o) => o.id !== id || o.state === 'sent') })),
      progress: (k) => saved.progress[k] ?? {},
      setProgress: (k, patch) => update((s) => ({ ...s, progress: { ...s.progress, [k]: { ...(s.progress[k] ?? {}), ...patch } } })),
      reset: async () => {
        await forgetSigningKey();
        update(() => EMPTY);
      },
    }),
    [online, saved, registering, registerProblem, registerDevice, syncProblem, syncNow, keepCapture, queue, signedCheck, update],
  );
  return <FieldContext.Provider value={value}>{children}</FieldContext.Provider>;
}

/** Decode standard base64 to bytes (the SPKI public key). */
function atobBytes(b64: string): number[] {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const out: number[] = [];
  let buf = 0;
  let bits = 0;
  for (const ch of b64.replace(/=+$/, '')) {
    buf = (buf << 6) | chars.indexOf(ch);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((buf >> bits) & 0xff);
    }
  }
  return out;
}

export function useField(): Field {
  const f = useContext(FieldContext);
  if (!f) throw new Error('useField must be used inside FieldProvider');
  return f;
}

export function useJob(subjectType: string, subjectId: string): Job | undefined {
  const { jobs } = useField();
  return jobs.find((j) => j.subject_type === subjectType && j.subject_id === subjectId);
}

export { type MobileApi };
