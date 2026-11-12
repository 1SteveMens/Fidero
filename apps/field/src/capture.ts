import { Platform } from 'react-native';
import * as Location from 'expo-location';
import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';
import { distanceMeters, type Capture, type GeoPoint, type Site } from '@fidero/shared';
import { newId } from './store';

export type Position = GeoPoint & { accuracyM?: number };

/** The phone's position now, or undefined if location is off or refused (FR-MOB-003, FR-MOB-012). */
export async function currentPosition(): Promise<Position | undefined> {
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) return undefined;
    const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracyM: loc.coords.accuracy ?? undefined };
  } catch {
    return undefined;
  }
}

function hex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** SHA-256 of the captured file, taken on the phone (FR-MOB-004, first half; hardware signing comes with the test build). */
async function fingerprint(uri: string): Promise<string> {
  if (Platform.OS !== 'web') {
    try {
      return await new File(uri).digest('SHA-256');
    } catch {
      // fall through
    }
  }
  const buf = await (await fetch(uri)).arrayBuffer();
  return hex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, buf));
}

/** Moves the capture into the app's own evidence folder, so it is kept until the server confirms receipt (FR-MOB-008). */
function keepOnPhone(uri: string, id: string, ext: string): string {
  if (Platform.OS === 'web') return uri;
  try {
    const dir = new Directory(Paths.document, 'fidero-field', 'evidence');
    if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
    const dest = new File(dir, `${id}.${ext}`);
    new File(uri).copySync(dest);
    return dest.uri;
  } catch {
    return uri;
  }
}

/** Builds a capture record from a file the app's camera just made. */
export async function makeCapture(opts: { uri: string; kind: 'photo' | 'video'; jobId: string; itemId: string; site: Site }): Promise<Capture> {
  const id = newId('cap');
  const [position, sha256] = await Promise.all([currentPosition(), fingerprint(opts.uri)]);
  const uri = keepOnPhone(opts.uri, id, opts.kind === 'video' ? 'mp4' : 'jpg');
  return {
    id,
    jobId: opts.jobId,
    itemId: opts.itemId,
    kind: opts.kind,
    uri,
    takenAt: new Date().toISOString(),
    position,
    distanceM: position ? distanceMeters(position, opts.site.location) : undefined,
    sha256,
  };
}

/** "4be1 … 9c02": the first and last four characters, as the report shows fingerprints. */
export function shortHash(h: string): string {
  return h.length > 8 ? `${h.slice(0, 4)} … ${h.slice(-4)}` : h;
}

export function timeOfDay(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
