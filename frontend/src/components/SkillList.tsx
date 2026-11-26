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

export interface SkillListProps {
  title: string;
  view: string;
  grouped: boolean;
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
  const firstKey = state.data?.items[0]?.identity_key;
  useEffect(() => { scroll.current?.scrollTo({ top: 0 }); }, [firstKey, page, title]);
  return (
    <section className="list-pane" aria-label="skill 列表">
      <header className="pane-head">
        <div className="inventory-heading">
          <h2>{title === '全部' ? '全部技能' : title}</h2>
          {state.status === 'ready'
            ? <span className="pane-count">{grouped ? '本组' : '共'} {formatCount(state.data.total)} 个 skill</span>
            : <Skeleton width="60px" height={10} />}
        </div>
        <button type="button" className="icon-button" title="重新扫描本机" aria-label="重新扫描本机" disabled={busy} onClick={onRefresh}>
          ↻
        </button>
      </header>

      <div className="rows-scroll" ref={scroll}>
        {state.status === 'loading' ? <ListSkeleton rows={9} /> : null}

        {state.status === 'error' ? <ErrorState message={state.error} onRetry={onRefresh} /> : null}

        {state.status === 'ready' && state.data.items.length === 0 ? (
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

        {state.status === 'ready' && state.data.items.length > 0 ? (
          <ul className="rows">
            {state.data.items.map((item, index) => (
              <SkillRow
                key={item.identity_key}
                item={item}
                index={index}
                selected={item.identity_key === selectedKey}
                busy={busy}
                grouped={grouped}
                showCategory={showCategory}
                onFavorite={onFavorite}
                healthLabels={healthLabels}
                onOpen={onOpenSkill}
              />
            ))}
          </ul>
        ) : null}
      </div>

      {state.status === 'ready' && state.data.total > pageSize ? (
        <Pagination page={page} pageSize={pageSize} total={state.data.total} onPageChange={onPageChange} />
      ) : null}
    </section>
  );
}
