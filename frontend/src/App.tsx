import { useEffect } from 'react';
import type { Health } from './api/types';
import { api } from './api/endpoints';
import { EmptyState } from './components/EmptyState';
import { TopBar } from './components/TopBar';
import { isTypingTarget } from './lib/dom';
import { HASH, isLibrarySurface, navigate, skillHash, useHashRoute, type LibraryPosition } from './lib/route';
import { focusSearch } from './lib/searchFocus';
import { useThemePref } from './lib/theme';
import { useApi } from './lib/useApi';
import { LibraryPage } from './pages/LibraryPage';
import { PromptsPage } from './pages/PromptsPage';
import { SettingsPage } from './pages/SettingsPage';
import { TrackingPage } from './pages/TrackingPage';

export function App() {
  const route = useHashRoute();
  const showIndexStatus = route.name !== 'prompts';
  const health = useApi<Health>(api.health, [], true, showIndexStatus);
  const theme = useThemePref();
  useEffect(() => {
    if (!showIndexStatus) return;
    const refresh = () => { if (!document.hidden) health.reload(); };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [health.reload, showIndexStatus]);

  useEffect(() => {
    if (window.location.hash === '') {
      window.history.replaceState(null, '', HASH.library);
    }
  }, []);

  // `/` is global: surfaces without a search box forward it to the library.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (isTypingTarget(event.target) || isLibrarySurface(route)) {
        return;
      }
      event.preventDefault();
      if (route.name !== 'prompts') navigate(HASH.library);
      focusSearch();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [route]);

  const openSkill = (identityKey: string, position?: LibraryPosition) => {
    navigate(skillHash(identityKey, position));
  };

  return (
    <div className="app">
      <TopBar
        route={route}
        health={health.state}
        onRetryHealth={health.reload}
        themePref={theme.pref}
        onThemePrefChange={theme.setPref}
      />

      <main className="main">
        {route.name === 'library' || route.name === 'skill' ? (
          <LibraryPage
            generation={health.state.status === 'ready' ? health.state.data.meta.generation : ''}
            onScanned={health.reload}
            selectedKey={route.name === 'skill' ? route.identityKey : null}
            onOpenSkill={openSkill}
          />
        ) : route.name === 'prompts' ? (
          <PromptsPage />
        ) : route.name === 'tracking' ? (
          <TrackingPage health={health.state} onRetryHealth={health.reload} onOpenSkill={openSkill} />
        ) : route.name === 'settings' ? (
          <SettingsPage health={health.state} onRetryHealth={health.reload} />
        ) : (
          <div className="page">
            <EmptyState
              title="页面不存在"
              hint={`没有匹配的路由：${route.raw}`}
              actionLabel="回到库"
              actionHref={HASH.library}
            />
          </div>
        )}
      </main>
    </div>
  );
}
