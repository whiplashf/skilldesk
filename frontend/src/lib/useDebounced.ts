import { useEffect, useState } from 'react';

/** Debounces a fast-changing value (search box) before it reaches a request. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delayMs]);

  return debounced;
}
