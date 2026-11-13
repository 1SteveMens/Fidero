import { Platform } from 'react-native';
import { Directory, File, Paths } from 'expo-file-system';

/**
 * The phone keeps jobs, captures and the upload queue in a file in the app's
 * own storage, so nothing is lost when the app closes or the phone restarts
 * (FR-MOB-005, FR-MOB-008). The web preview, a development tool, uses localStorage.
 */
const NAME = 'state-v2.json';

function file(): File | null {
  if (Platform.OS === 'web') return null;
  try {
    const dir = new Directory(Paths.document, 'tenmina-field');
    if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
    return new File(dir, NAME);
  } catch {
    return null;
  }
}

export function loadState<T>(empty: T): T {
  try {
    if (Platform.OS === 'web') {
      const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(`tenmina-field.${NAME}`);
      return raw ? { ...empty, ...(JSON.parse(raw) as T) } : empty;
    }
    const f = file();
    if (!f || !f.exists) return empty;
    return { ...empty, ...(JSON.parse(f.textSync()) as T) };
  } catch {
    return empty;
  }
}

export function saveState<T>(state: T): void {
  try {
    const text = JSON.stringify(state);
    if (Platform.OS === 'web') {
      if (typeof localStorage !== 'undefined') localStorage.setItem(`tenmina-field.${NAME}`, text);
      return;
    }
    const f = file();
    if (!f) return;
    if (!f.exists) f.create();
    f.writeSync(text);
  } catch {
    // Storage full or unavailable: the queue still works for this session.
  }
}

/** Moves a capture into the app's own evidence folder, kept until the server confirms receipt (FR-MOB-008). */
export function keepFile(uri: string, id: string, ext: string): string {
  if (Platform.OS === 'web') return uri;
  try {
    const dir = new Directory(Paths.document, 'tenmina-field', 'evidence');
    if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
    const dest = new File(dir, `${id}.${ext}`);
    new File(uri).copySync(dest);
    return dest.uri;
  } catch {
    return uri;
  }
}

/** Deletes the phone's copy once the server has stored the evidence (FR-MOB-009). */
export function dropFile(uri: string): void {
  if (Platform.OS === 'web') return;
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    // already gone
  }
}

/** The web preview has no file system: captured blobs are held in memory for the session only. */
export const webBlobs = new Map<string, Blob>();
