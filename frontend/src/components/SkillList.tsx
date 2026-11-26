import { useEffect, useRef } from 'react';
import type { IndexResponse, SkillSummary } from '../api/types';
import { formatCount } from '../lib/format';
import { HASH } from '../lib/route';
import type { AsyncState } from '../lib/useApi';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { ListSkeleton, Skeleton } from './Skeleton';
import { Pagination } from './Pagination';
import { SkillRow } from './SkillRow';
import { SourceGroups } from './SourceGroups';

export interface SkillListProps {
  title: string;
  view: string;
  grouped: boolean;
  groupPages: Record<string, number>;
  scrollKey: string;
  revealKey: string;
  onGroupPage: (key: string, page: number) => void;
  onLayout: (grouped: boolean) => void;
  showCategory: boolean;
  state: AsyncState<IndexResponse>;
  page: number;
  pageSize: number;
  selectedKey: string | null;
  hasFilters: boolean;
  onFavorite: (item: SkillSummary) => void;
  busy: boolean;
  healthLabels: Record<string, string>;
  onOpenSkill: (identityKey: string) => void;
  onPageChange: (page: number) => void;
  onClearFilters: () => void;
  onRefresh: () => void;
}

export function SkillList({
  title,
  view,
  grouped,
  groupPages,
  scrollKey,
  revealKey,
  onGroupPage,
  onLayout,
  showCategory,
  state,
  page,
  pageSize,
  selectedKey,
  hasFilters,
  onFavorite,
  busy,
  healthLabels,
  onOpenSkill,
  onPageChange,
  onClearFilters,
  onRefresh,
}: SkillListProps) {
  const scroll = useRef<HTMLDivElement>(null);
  const lastReveal = useRef('');
  useEffect(() => { scroll.current?.scrollTo({ top: 0 }); }, [scrollKey]);
  const groups = state.data?.repositories ?? [];
  useEffect(() => {
    const container = scroll.current;
    if (!container?.clientHeight || state.status !== 'ready' || !revealKey) {
      lastReveal.current = '';
      return;
    }
    if (grouped !== (state.data.repositories?.[0]?.page !== undefined)) return;
    const token = JSON.stringify([scrollKey, revealKey]);
    if (lastReveal.current === token) return;
    const row = container.querySelector<HTMLButtonElement>('button[data-skill-key="' + CSS.escape(revealKey) + '"]');
    if (!row) return;
    const area = container.getBoundingClientRect();
    const bounds = row.getBoundingClientRect();
    const heading = row.closest('.source-group')?.querySelector('h3')?.offsetHeight ?? 0;
    if (bounds.top < area.top + heading || bounds.bottom > area.bottom) {
      container.scrollTop += bounds.top - area.top - heading;
    }
    lastReveal.current = token;
  }, [state, grouped, scrollKey, revealKey]);
  const showingGroups = groups[0]?.page !== undefined;
  const inline = showingGroups && groups.length > 1;
  function renderRows(items: SkillSummary[]) {
    return <ul className="rows">{items.map((item, index) => <SkillRow key={item.identity_key} item={item} index={index}
      selected={item.identity_key === selectedKey} busy={busy} grouped={inline} showCategory={showCategory}
      onFavorite={onFavorite} healthLabels={healthLabels} onOpen={onOpenSkill} />)}</ul>;
  }
  return (
    <section className="list-pane" aria-label="skill 列表">
      <header className="pane-head">
        <div className="inventory-heading">
          <h2>{title === '全部' ? '全部技能' : title}</h2>
          {state.status === 'ready'
            ? <span className="pane-count">共 {formatCount(state.data.total)} 个 skill{inline && ' · ' + groups.length + ' 个来源'}</span>
            : <Skeleton width="60px" height={10} />}
        </div>
        <div className="inventory-actions">
          {groups.length > 1 && <label className="source-switch">
            <input type="checkbox" role="switch" checked={grouped} onChange={event => onLayout(event.target.checked)} />
            按来源分组
          </label>}
          <button type="button" className="icon-button" title="重新扫描本机" aria-label="重新扫描本机" disabled={busy} onClick={onRefresh}>
          ↻
          </button>
        </div>
      </header>

      <div className="rows-scroll" ref={scroll} aria-busy={Boolean(groups.length) && showingGroups !== grouped}>
        {state.status === 'loading' ? <ListSkeleton rows={9} /> : null}

        {state.status === 'error' ? <ErrorState message={state.error} onRetry={onRefresh} /> : null}

        {state.status === 'ready' && state.data.total === 0 ? (
          view === 'favorites' && !state.data.hasFavorites ? (
            <EmptyState title="还没有收藏" hint="点技能旁的 ☆，就能在这里找到它。" />
          ) : hasFilters ? (
            <EmptyState
              title="没有匹配的 skill"
              hint="可以调整搜索词或清除当前筛选。"
              actionLabel="清空筛选"
              onAction={onClearFilters}
            />
          ) : view === 'mine' || view === 'github' ? (
            <EmptyState title={view === 'mine' ? '还没有标为自写的 skill' : '还没有跟踪的 GitHub skill'}
              hint={view === 'mine' ? '打开自己写的本地技能，在「来源与可用范围」勾选「我写的」。' : '打开技能的「来源与可用范围」，可以关联它的 GitHub 仓库。'}
              actionLabel="查看全部技能" actionHref={HASH.library} />
          ) : (
            <div className="state"><h3 className="state-title">本机还没有发现 skill</h3>
              <p className="state-hint">可以添加已有 skill 的项目，或从你知道的仓库安装。</p>
              <div className="empty-actions"><a className="button" href={HASH.settings + '?section=projects'}>添加项目</a>
                <a className="button" href={HASH.settings + '?section=install'}>从已知仓库安装</a></div>
            </div>
          )
        ) : null}

        {state.status === 'ready' && state.data.total > 0 && (inline
          ? <SourceGroups groups={groups} items={state.data.items} pages={groupPages} pageSize={pageSize}
              onPage={onGroupPage} renderRows={renderRows} />
          : renderRows(state.data.items))}
      </div>

      {state.status === 'ready' && !inline && state.data.total > pageSize ? (
        <Pagination page={page} pageSize={pageSize} total={state.data.total} onPageChange={onPageChange} />
      ) : null}
    </section>
  );
}
