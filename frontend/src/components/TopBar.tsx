import type { Health } from '../api/types';
import { formatCount, formatDateTime, formatRelative, toIsoString } from '../lib/format';
import { HASH, type Route } from '../lib/route';
import type { AsyncState } from '../lib/useApi';
import type { ThemePref } from '../lib/theme';
import { ThemeSwitch } from './ThemeSwitch';

export interface TopBarProps {
  route: Route;
  health: AsyncState<Health>;
  onRetryHealth: () => void;
  themePref: ThemePref;
  onThemePrefChange: (pref: ThemePref) => void;
}

const TABS: ReadonlyArray<{ hash: string; label: string; matches: ReadonlyArray<Route['name']> }> = [
  { hash: HASH.library, label: '库', matches: ['library', 'skill'] },
  { hash: HASH.tracking, label: '跟踪', matches: ['tracking'] },
  { hash: HASH.settings, label: '设置', matches: ['settings'] },
];

function IndexFreshness({ health, onRetry }: { health: AsyncState<Health>; onRetry: () => void }) {
  if (health.status === 'loading') {
    return <span className="freshness freshness--muted">索引状态加载中</span>;
  }
  if (health.status === 'error') {
    return (
      <span className="freshness freshness--muted">
        索引状态不可用
        <button type="button" className="link-button" onClick={onRetry}>
          重试
        </button>
      </span>
    );
  }

  const { meta, counts } = health.data;
  return (
    <span className="freshness">
      <span>索引更新于</span>
      <time title={formatDateTime(meta.scanned_at)} dateTime={toIsoString(meta.scanned_at)}>
        {formatRelative(meta.scanned_at)}
      </time>
      <span className="freshness-sep" aria-hidden="true">
        ·
      </span>
      <span className="mono">{formatCount(counts.skills)}</span>
      <span>个 skill</span>
      <span className="freshness-sep" aria-hidden="true">
        ·
      </span>
      <span className="mono">{formatCount(counts.issues)}</span>
      <span>个待处理</span>
    </span>
  );
}

export function TopBar({ route, health, onRetryHealth, themePref, onThemePrefChange }: TopBarProps) {
  const version = health.status === 'ready' ? health.data.version : undefined;

  return (
    <header className="topbar">
      <a className="brand" href={HASH.library}>
        skilldesk
      </a>
      {version === undefined ? null : <span className="brand-version mono">v{version}</span>}

      <nav className="tabs" aria-label="主导航">
        {TABS.map((tab) => {
          const active = tab.matches.includes(route.name);
          return (
            <a key={tab.hash} className={active ? 'tab is-active' : 'tab'} href={tab.hash} aria-current={active ? 'page' : undefined}>
              {tab.label}
            </a>
          );
        })}
      </nav>

      <div className="topbar-tail">
        <IndexFreshness health={health} onRetry={onRetryHealth} />
        <ThemeSwitch pref={themePref} onChange={onThemePrefChange} />
      </div>
    </header>
  );
}
