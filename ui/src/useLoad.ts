import { useCallback, useEffect, useState } from "react";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Load data when the dependencies change; keeps the last good data while reloading. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true);
    load()
      .then((value) => {
        if (!live) return;
        setData(value);
        setError(null);
      })
      .catch((reason: unknown) => live && setError(reason))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}
