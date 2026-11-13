import { Platform } from 'react-native';
import * as Location from 'expo-location';
import { File } from 'expo-file-system';
import { newUuid } from '@tenmina/mobile';
import { sha256Hex } from './canonical';
import { keepFile, webBlobs } from './persist';
import type { Capture, Job } from './types';

export interface Position {
  lat: number;
  lng: number;
  accuracyM?: number;
  mock?: boolean;
}

/** The phone's position now, or undefined if location is off or refused (FR-MOB-003, FR-MOB-012). */
export async function currentPosition(): Promise<Position | undefined> {
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) return undefined;
    const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    return { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracyM: loc.coords.accuracy ?? undefined, mock: (loc as { mocked?: boolean }).mocked ?? false };
  } catch {
    return undefined;
  }
}

/** Metres between two points (haversine), as the server measures it. */
export function distanceM(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const R = 6371000;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** "312 m from the address" or a warning when too far or the fix is poor (FR-MOB-003). */
export function siteCheck(job: Job | undefined, pos: Position | undefined, maxAccuracy = 50): { far: boolean; text: string; distance?: number } {
  if (!pos) return { far: true, text: 'Location is off. Turn it on, or say why.' };
  if (!job?.point) return { far: false, text: `Position recorded (±${Math.round(pos.accuracyM ?? 0)} m)` };
  const d = distanceM(pos, job.point);
  const radius = job.radius_m ?? 100;
  if (d > radius) return { far: true, distance: d, text: `${Math.round(d)} m from the site. That is further than ${radius} m.` };
  if ((pos.accuracyM ?? 0) > maxAccuracy) return { far: true, distance: d, text: `Weak location fix (±${Math.round(pos.accuracyM ?? 0)} m).` };
  return { far: false, distance: d, text: `On site, ${Math.round(d)} m from the address` };
}

/**
 * Builds a capture from a file this app's camera just made: its SHA-256 and
 * size, the time and the position. It is signed when the person keeps it.
 */
export async function makeCapture(opts: { uri: string; kind: 'photo' | 'video'; mediaType?: string; subjectType: string; subjectId: string; requirementKey: string; job?: Job; blob?: Blob }): Promise<Omit<Capture, 'signed' | 'state'>> {
  const id = newUuid();
  const takenAt = new Date().toISOString();
  const position = await currentPosition();
  let sha: string;
  let size: number;
  let uri = opts.uri;
  if (Platform.OS === 'web') {
    const blob = opts.blob ?? (await (await fetch(opts.uri)).blob());
    const bytes = new Uint8Array(await blob.arrayBuffer());
    sha = sha256Hex(bytes);
    size = bytes.byteLength;
    webBlobs.set(id, blob);
  } else {
    uri = keepFile(opts.uri, id, opts.kind === 'video' ? 'mp4' : 'jpg');
    const f = new File(uri);
    sha = (await f.digest('SHA-256')).toLowerCase();
    size = f.size;
  }
  return {
    id,
    subjectType: opts.subjectType,
    subjectId: opts.subjectId,
    requirementKey: opts.requirementKey,
    kind: opts.kind,
    uri,
    mediaType: opts.mediaType ?? (opts.kind === 'video' ? 'video/mp4' : 'image/jpeg'),
    size,
    sha256: sha,
    takenAt,
    lat: position?.lat,
    lng: position?.lng,
    accuracyM: position?.accuracyM,
    distanceM: position && opts.job?.point ? distanceM(position, opts.job.point) : undefined,
  };
}
