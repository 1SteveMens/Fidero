import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useFocusEffect } from 'expo-router';
import { createSampleApi, type FideroApi } from '@fidero/shared';

const ApiContext = createContext<FideroApi | null>(null);

/** Serves sample data until the /v1 API exists. Swap the implementation here only. */
export function ApiProvider({ children }: { children: ReactNode }) {
  const api = useMemo(() => createSampleApi(), []);
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): FideroApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error('useApi must be used inside ApiProvider');
  return api;
}

export interface Loaded<T> {
  data?: T;
  error?: string;
  reload: () => void;
}

/** Loads data each time the screen comes into focus, so approvals made elsewhere show at once. */
export function useLoad<T>(load: (api: FideroApi) => Promise<T>, key: string): Loaded<T> {
  const api = useApi();
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [tick, setTick] = useState(0);

  useFocusEffect(
    useCallback(() => {
      let live = true;
      setError(undefined);
      load(api)
        .then((value) => live && setData(value))
        .catch((e: unknown) => live && setError(e instanceof Error ? e.message : 'Something went wrong.'));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [api, key, tick]),
  );

  return { data, error, reload: () => setTick((t) => t + 1) };
}
