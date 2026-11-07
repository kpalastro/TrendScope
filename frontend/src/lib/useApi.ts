"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

type State<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Fetch a resource and keep it in component state. The request is aborted when
 * the path changes or the component unmounts, so fast filter changes cannot
 * race and render stale results.
 */
export function useApi<T>(path: string | null, deps: unknown[] = []): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const [tick, setTick] = useState(0);
  const previous = useRef<string | null>(null);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      setError(null);
      setData(null);
      return;
    }
    const controller = new AbortController();
    let active = true;
    if (previous.current !== path) {
      // A new view must not show the previous view's rows while it loads (or
      // under an error), so clear them at the change rather than on success.
      setData(null);
    }
    previous.current = path;
    // Also true for reload(), so refresh affordances can show progress.
    setLoading(true);
    setError(null);

    api
      .get<T>(path, controller.signal)
      .then((result) => {
        if (!active) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        if ((err as Error)?.name === "AbortError") return;
        const message =
          err instanceof ApiError
            ? err.message
            : "Something went wrong while loading this view.";
        setError(message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload };
}
