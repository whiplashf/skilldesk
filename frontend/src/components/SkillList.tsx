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
          hasFilters ? (
            <EmptyState
              title={view === 'mine' ? '当前范围没有自写 skill' : '没有匹配的 skill'}
              hint={view === 'mine' ? '在「全部」中打开你写的 skill，展开「来源与可用范围」并勾选「我写的」。' : '当前筛选条件下没有任何结果。'}
              actionLabel={view === 'mine' ? '查看全部技能' : '清空筛选'}
              onAction={onClearFilters}
            />
          ) : (
            <EmptyState
              title="本机没有发现 skill"
              hint="检查设置里已探测的宿主根，或先运行 skilldesk scan 重建索引。"
              actionLabel="查看宿主根"
              actionHref={HASH.settings}
            />
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
