import { useCallback, useEffect, useState } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';

const THEME_STORAGE_KEY = 'skilldesk.theme';

const THEME_PREFS: readonly ThemePref[] = ['light', 'dark', 'system'];

function isThemePref(value: string | null): value is ThemePref {
  return value !== null && (THEME_PREFS as readonly string[]).includes(value);
}

function readPref(): ThemePref {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePref(stored) ? stored : 'system';
  } catch {
    return 'system';
  }
}

/**
 * Theme preference is persisted separately from the resolved theme: `system` keeps
 * following `prefers-color-scheme` live, and the DOM carries only the resolved value.
 */
export function useThemePref(): { pref: ThemePref; setPref: (pref: ThemePref) => void } {
  const [pref, setPrefState] = useState<ThemePref>(readPref);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      const resolved = pref === 'system' ? (media.matches ? 'dark' : 'light') : pref;
      document.documentElement.dataset.theme = resolved;
    };
    apply();

    if (pref !== 'system') {
      return;
    }
    media.addEventListener('change', apply);
    return () => {
      media.removeEventListener('change', apply);
    };
  }, [pref]);

  const setPref = useCallback((next: ThemePref) => {
    setPrefState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private mode / storage disabled: the in-memory preference still applies.
    }
  }, []);

  return { pref, setPref };
}
