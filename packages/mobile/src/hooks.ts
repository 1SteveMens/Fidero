import { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { toProblem, type Method, type Problem, type RequestOptions } from './api';
import { useApi } from './session';

export interface Loaded<T> {
  data?: T;
  problem?: Problem;
  loading: boolean;
  reload: () => void;
}

/**
 * GET a path each time the screen comes into focus, so an approval made on
 * another screen shows at once. Pass null to wait (for an id not known yet).
 */
export function useGet<T>(path: string | null, query?: RequestOptions['query']): Loaded<T> {
  const api = useApi();
  const [data, setData] = useState<T>();
  const [problem, setProblem] = useState<Problem>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const key = path ? `${path}?${JSON.stringify(query ?? {})}` : '';

  useFocusEffect(
    useCallback(() => {
      if (!path) return;
      let live = true;
      setLoading(true);
      api
        .get<T>(path, query)
        .then((v) => {
          if (!live) return;
          setData(v);
          setProblem(undefined);
        })
        .catch((e: unknown) => live && setProblem(toProblem(e)))
        .finally(() => live && setLoading(false));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [api, key, tick]),
  );
  return { data, problem, loading, reload: () => setTick((t) => t + 1) };
}

/** Like useGet, but for a screen that needs several calls at once. */
export function useLoad<T>(load: (api: ReturnType<typeof useApi>) => Promise<T>, key: string): Loaded<T> {
  const api = useApi();
  const [data, setData] = useState<T>();
  const [problem, setProblem] = useState<Problem>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fn = useRef(load);
  fn.current = load;
  useFocusEffect(
    useCallback(() => {
      if (!key) return;
      let live = true;
      setLoading(true);
      fn.current(api)
        .then((v) => {
          if (!live) return;
          setData(v);
          setProblem(undefined);
        })
        .catch((e: unknown) => live && setProblem(toProblem(e)))
        .finally(() => live && setLoading(false));
      return () => {
        live = false;
      };
    }, [api, key, tick]),
  );
  return { data, problem, loading, reload: () => setTick((t) => t + 1) };
}

/**
 * One action that moves the workflow on (approve, decline, start a step). Keeps
 * its own busy flag and the problem the API answered with, for ProblemBox.
 */
export function useAction() {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const run = useCallback(
    async <T,>(method: Method, path: string, body?: unknown, opts: Omit<RequestOptions, 'body'> = {}): Promise<T | undefined> => {
      setBusy(true);
      setProblem(undefined);
      try {
        return await api.request<T>(method, path, { ...opts, body: method === 'GET' ? undefined : (body ?? {}) });
      } catch (e) {
        setProblem(toProblem(e));
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );
  return { run, busy, problem, setProblem, clear: () => setProblem(undefined) };
}

/** Lists come either as {items, next_cursor} or as a plain array. */
export function itemsOf<T>(d: { items?: T[] } | T[] | undefined | null): T[] {
  if (!d) return [];
  return Array.isArray(d) ? d : (d.items ?? []);
}
