import { useCallback, useEffect, useRef, useState } from 'react';
import { describeError, isAbortError } from '../api/client';

export type AsyncState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'ready'; data: T; error: null }
  | { status: 'error'; data: null; error: string };

interface AsyncResult<T> {
  state: AsyncState<T>;
  reload: () => void;
}

const LOADING = { status: 'loading', data: null, error: null } as const;

/**
 * Minimal request hook: aborts stale requests, exposes loading/ready/error and a retry.
 * `deps` is the request identity; `load` is read through a ref so inline arrows are fine.
 */
export function useApi<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  retainData = false,
): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>(LOADING);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    const run = loadRef.current;
    const controller = new AbortController();
    let active = true;
    setState(previous => retainData && previous.status === 'ready' ? previous : LOADING);

    run(controller.signal).then(
      (data) => {
        if (active) {
          setState({ status: 'ready', data, error: null });
        }
      },
      (error: unknown) => {
        if (!active || isAbortError(error)) {
          return;
        }
        setState({ status: 'error', data: null, error: describeError(error) });
      },
    );

    return () => {
      active = false;
      controller.abort();
    };
    // `load` is intentionally read from the ref; `deps` identifies the request.
  }, [...deps, attempt]);

  const reload = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  return { state, reload };
}
