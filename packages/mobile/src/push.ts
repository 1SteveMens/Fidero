import { Platform } from 'react-native';
import { APP_VERSION, newUuid, platformName, type MobileApi } from './api';
import { secureGet, secureSet } from './storage';

const INSTALL_KEY = 'tenmina.install_id';
const PUSH_KEY = 'tenmina.push';

/** One id per install, so a reinstall or a new token replaces the old row (FR-APP-002). */
export async function installId(): Promise<string> {
  let id = await secureGet(INSTALL_KEY);
  if (!id) {
    id = newUuid();
    await secureSet(INSTALL_KEY, id);
  }
  return id;
}

export type PushChoice = 'on' | 'off' | null;

/** What the person chose on "Turn on notifications?" (SCR-APP-01). The app never asks again by itself. */
export async function pushChoice(): Promise<PushChoice> {
  const v = await secureGet(PUSH_KEY);
  return v === 'on' || v === 'off' ? v : null;
}

export async function setPushChoice(v: 'on' | 'off'): Promise<void> {
  await secureSet(PUSH_KEY, v);
}

/**
 * Register this install for push with POST /v1/me/push-devices.
 *
 * The real APNs or FCM token needs expo-notifications in a development or store
 * build, which is not in this build yet. Until then the install registers a
 * development token, so the server side (one row per install, revoked at
 * sign-out) is exercised end to end; the server's push adapter is a fake too.
 */
export async function registerPush(api: MobileApi, token?: string): Promise<{ id: string }> {
  const install = await installId();
  return api.post<{ id: string }>('/v1/me/push-devices', {
    app: api.app,
    platform: platformName(),
    token: token ?? `dev-${api.app}-${install}`,
    install_id: install,
    app_version: APP_VERSION,
    os_version: `${Platform.OS} ${String(Platform.Version ?? '')}`.trim(),
  });
}
