import { useCallback, useEffect, useRef, useState } from 'react';

interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

export function useAsync<T>(
  loader: () => Promise<T>,
  key: string | number = 'default',
  options: { pollMs?: number; enabled?: boolean } = {},
) {
  const { pollMs = 0, enabled = true } = options;
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: enabled,
  });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    if (!enabled) {
      setState((current) => ({ ...current, loading: false }));
      return () => {
        cancelled = true;
      };
    }
    let first = true;
    const run = async () => {
      if (first) {
        setState((current) => ({
          ...current,
          loading: current.data === null,
          error: null,
        }));
        first = false;
      }
      try {
        const data = await loaderRef.current();
        if (!cancelled) {
          setState({ data, error: null, loading: false });
        }
      } catch (error) {
        if (!cancelled) {
          setState((current) => ({
            data: current.data,
            error: error instanceof Error ? error : new Error(String(error)),
            loading: false,
          }));
        }
      }
    };
    void run();
    const timer = pollMs > 0 ? window.setInterval(() => void run(), pollMs) : null;
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [key, enabled, pollMs, tick]);

  return {
    ...state,
    reload,
    setData: useCallback((data: T | null) => {
      setState((current) => ({ ...current, data }));
    }, []),
  };
}

export function useDebouncedValue<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · Mannazia` : 'Mannazia';
    return () => {
      document.title = previous;
    };
  }, [title]);
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine,
  );
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);
  return online;
}
