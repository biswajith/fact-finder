import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { errorText } from './store';

export interface Async<T> {
  data: T | null;
  error: string | null;
  /** HTTP status of the failure, when there was one. */
  status: number | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Run `fn` whenever `deps` change (and on reload()). Stale answers are dropped; the previous
 * data stays visible while a new request is loading.
 */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[], enabled = true): Async<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; status: number | null; loading: boolean }>({
    data: null, error: null, status: null, loading: enabled,
  });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!enabled) return;
    const ctl = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    fnRef.current(ctl.signal).then(
      (data) => !ctl.signal.aborted && setState({ data, error: null, status: null, loading: false }),
      (e) => {
        if (ctl.signal.aborted || (e instanceof DOMException && e.name === 'AbortError')) return;
        setState((s) => ({ data: s.data, error: errorText(e), status: e instanceof ApiError ? e.status : null, loading: false }));
      },
    );
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** `value`, but only after it has stopped changing for `ms`. */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}
