import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Fetch on mount and then every `intervalMs` while `active` is true (paused
 * while the tab is hidden; refreshed on return). Returns the latest data, the
 * latest error, and a manual refresh.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number, active = true, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  // Only the newest request may set state: a slow older response (or one for the
  // previous `deps`, e.g. another run) must not overwrite newer data.
  const latest = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++latest.current;
    try {
      const value = await fetcherRef.current();
      if (id !== latest.current) return;
      setData(value);
      setError(undefined);
    } catch (e) {
      if (id === latest.current) setError(e as Error);
    }
  }, []);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => document.visibilityState === "visible" && refresh(), intervalMs);
    const onVisible = () => document.visibilityState === "visible" && refresh();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [active, intervalMs, refresh]);

  return { data, error, refresh };
}
