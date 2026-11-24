import { useEffect, useState } from 'react';

export type Route =
  | { name: 'library' }
  | { name: 'skill'; identityKey: string }
  | { name: 'tracking' }
  | { name: 'settings' }
  | { name: 'notFound'; raw: string };

export const HASH = {
  library: '#/library',
  tracking: '#/tracking/health',
  settings: '#/settings',
} as const;

export function skillHash(identityKey: string): string {
  return `#/skill/${encodeURIComponent(identityKey)}`;
}

export function isLibrarySurface(route: Route): boolean {
  return route.name === 'library' || route.name === 'skill';
}

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Parses `location.hash`. The identity key is percent-encoded into one segment, but a raw
 * (unencoded) key pasted by hand still resolves because trailing segments are re-joined.
 */
function parseRoute(hash: string): Route {
  const path = hash.startsWith('#') ? hash.slice(1) : hash;
  const segments = path.split('/').filter((segment) => segment.length > 0);
  const head = segments[0];

  if (head === undefined) {
    return { name: 'library' };
  }
  if (head === 'library') {
    return { name: 'library' };
  }
  if (head === 'skill') {
    const rest = segments.slice(1);
    return rest.length === 0
      ? { name: 'library' }
      : { name: 'skill', identityKey: decode(rest.join('/')) };
  }
  if (head === 'tracking') {
    return { name: 'tracking' };
  }
  if (head === 'settings') {
    return { name: 'settings' };
  }
  return { name: 'notFound', raw: path };
}

export function navigate(hash: string): void {
  if (window.location.hash === hash) {
    return;
  }
  window.location.hash = hash;
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onHashChange = () => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => {
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);

  return route;
}
