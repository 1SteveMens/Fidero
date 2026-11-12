import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { useNetInfo } from '@react-native-community/netinfo';
import { Directory, File, Paths } from 'expo-file-system';
import { createSampleFieldApi, type Capture, type FieldApi, type FieldRole } from '@fidero/shared';

/** Something waiting to reach Fidero: a capture or a submitted checklist (FR-MOB-005). */
export interface QueueItem {
  id: string;
  jobId: string;
  kind: 'capture' | 'submission' | 'concern';
  label: string;
  createdAt: string;
  state: 'waiting' | 'sending' | 'sent';
  sentAt?: string;
}

interface Saved {
  /** Demo switch: behave as if the phone had no signal, to test the queue. */
  noSignal?: boolean;
  role: FieldRole | null;
  captures: Capture[];
  queue: QueueItem[];
  submitted: Record<string, string>;
}

interface Field {
  role: FieldRole | null;
  api: FieldApi | null;
  online: boolean;
  noSignal: boolean;
  setNoSignal: (v: boolean) => void;
  captures: Capture[];
  queue: QueueItem[];
  submitted: Record<string, string>;
  signIn: (role: FieldRole) => void;
  signOut: () => void;
  keepCapture: (c: Capture, label: string) => void;
  submitJob: (jobId: string, label: string) => void;
  raiseConcern: (jobId: string, label: string) => void;
  capturesFor: (jobId: string, itemId?: string) => Capture[];
}

const FieldContext = createContext<Field | null>(null);
const EMPTY: Saved = { role: null, captures: [], queue: [], submitted: {} };

/** On the phone, state lives in a file so the queue survives the app closing or a restart (FR-MOB-005). */
function stateFile(): File | null {
  if (Platform.OS === 'web') return null;
  try {
    const dir = new Directory(Paths.document, 'fidero-field');
    if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
    return new File(dir, 'state.json');
  } catch {
    return null;
  }
}

function load(): Saved {
  const f = stateFile();
  if (!f || !f.exists) return EMPTY;
  try {
    return { ...EMPTY, ...(JSON.parse(f.textSync()) as Saved) };
  } catch {
    return EMPTY;
  }
}

const now = () => new Date().toISOString();
let seq = 0;
export const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

export function FieldProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState<Saved>(load);
  const net = useNetInfo();
  // Unknown counts as online so the first render does not flash "Offline".
  const online = !saved.noSignal && net.isConnected !== false && net.isInternetReachable !== false;

  // Write every change to the phone's storage.
  useEffect(() => {
    const f = stateFile();
    if (!f) return;
    try {
      if (!f.exists) f.create();
      f.write(JSON.stringify(saved));
    } catch {
      // Storage full or unavailable: the queue still works for this session.
    }
  }, [saved]);

  // Sample upload: there is no server yet, so items are marked received a moment after the phone is online.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!online) return;
    const next = saved.queue.find((q) => q.state !== 'sent');
    if (!next || timer.current) return;
    setSaved((s) => ({ ...s, queue: s.queue.map((q) => (q.id === next.id ? { ...q, state: 'sending' } : q)) }));
    timer.current = setTimeout(() => {
      timer.current = null;
      setSaved((s) => ({ ...s, queue: s.queue.map((q) => (q.id === next.id ? { ...q, state: 'sent', sentAt: now() } : q)) }));
    }, 1400);
  }, [online, saved.queue]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const api = useMemo(() => (saved.role ? createSampleFieldApi(saved.role) : null), [saved.role]);

  const value: Field = {
    role: saved.role,
    api,
    online,
    noSignal: !!saved.noSignal,
    setNoSignal: (v) => setSaved((s) => ({ ...s, noSignal: v })),
    captures: saved.captures,
    queue: saved.queue,
    submitted: saved.submitted,
    signIn: (role) => setSaved((s) => ({ ...s, role })),
    signOut: () => setSaved(EMPTY),
    keepCapture: (c, label) =>
      setSaved((s) => ({
        ...s,
        captures: [...s.captures, c],
        queue: [...s.queue, { id: newId('q'), jobId: c.jobId, kind: 'capture', label, createdAt: now(), state: 'waiting' }],
      })),
    submitJob: (jobId, label) =>
      setSaved((s) => ({
        ...s,
        submitted: { ...s.submitted, [jobId]: now() },
        queue: [...s.queue, { id: newId('q'), jobId, kind: 'submission', label, createdAt: now(), state: 'waiting' }],
      })),
    raiseConcern: (jobId, label) =>
      setSaved((s) => ({ ...s, queue: [...s.queue, { id: newId('q'), jobId, kind: 'concern', label, createdAt: now(), state: 'waiting' }] })),
    capturesFor: (jobId, itemId) => saved.captures.filter((c) => c.jobId === jobId && (itemId === undefined || c.itemId === itemId)),
  };
  return <FieldContext.Provider value={value}>{children}</FieldContext.Provider>;
}

export function useField(): Field {
  const f = useContext(FieldContext);
  if (!f) throw new Error('useField must be used inside FieldProvider');
  return f;
}

/** Loads from the sample field API each time the screen comes into focus. */
export function useFieldLoad<T>(load: (api: FieldApi) => Promise<T>, key: string): { data?: T; error?: string; reload: () => void } {
  const { api } = useField();
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [tick, setTick] = useState(0);
  useFocusEffect(
    useCallback(() => {
      if (!api) return;
      let live = true;
      setError(undefined);
      load(api)
        .then((v) => live && setData(v))
        .catch((e: unknown) => live && setError(e instanceof Error ? e.message : 'Something went wrong.'));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [api, key, tick]),
  );
  return { data, error, reload: () => setTick((t) => t + 1) };
}
