import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

/**
 * Secrets (tokens, the field app's signing key) live in the phone's keychain or
 * keystore through expo-secure-store. The web preview, used only in development,
 * keeps them in localStorage instead: it is never a production target.
 */
const web = Platform.OS === 'web';

function ls(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export async function secureGet(key: string): Promise<string | null> {
  if (web) return ls()?.getItem(key) ?? null;
  try {
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function secureSet(key: string, value: string): Promise<void> {
  if (web) {
    ls()?.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY });
}

export async function secureDelete(key: string): Promise<void> {
  if (web) {
    ls()?.removeItem(key);
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key);
  } catch {
    // already gone
  }
}
