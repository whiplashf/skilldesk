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

export function libraryParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.split('?')[1] ?? '');
}

function librarySuffix(): string {
  const onLibrary = /^#\/(library|skill)(\/|\?|$)/.test(window.location.hash);
  return onLibrary ? libraryParams().toString() : sessionStorage.getItem('skilldesk.library-query') ?? '';
}

export function libraryHref(): string {
  const query = librarySuffix();
  return HASH.library + (query ? '?' + query : '');
}

export function updateLibraryParams(changes: Record<string, string>, reset = false): void {
  const params = reset ? new URLSearchParams() : libraryParams();
  for (const [key, value] of Object.entries(changes)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  sessionStorage.setItem('skilldesk.library-query', query);
  window.history.replaceState(null, '', HASH.library + (query ? '?' + query : ''));
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

export function skillHash(identityKey: string): string {
  const query = librarySuffix();
  return `#/skill/${encodeURIComponent(identityKey)}` + (query ? '?' + query : '');
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
  const segments = (path.split('?')[0] || '').split('/').filter((segment) => segment.length > 0);
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
