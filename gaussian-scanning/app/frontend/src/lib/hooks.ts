import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Fetch on mount and then every `intervalMs` while `active` is true.
 * Returns the latest data, the latest error, and a manual refresh.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number, active = true, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(undefined);
    } catch (e) {
      setError(e as Error);
    }
  }, []);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(refresh, intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs, refresh]);

  return { data, error, refresh };
}
