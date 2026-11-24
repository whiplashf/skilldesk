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
  return (
    <section className="list-pane" aria-label="skill 列表">
      <header className="pane-head">
        {state.status === 'ready' ? (
          <span className="pane-count">
            {hasFilters ? (
              <>
                筛选命中 <span className="mono">{formatCount(state.data.total)}</span> 个
              </>
            ) : (
              <>
                共 <span className="mono">{formatCount(state.data.total)}</span> 个
              </>
            )}
          </span>
        ) : (
          <Skeleton width="96px" height={10} />
        )}
        <button type="button" className="icon-button" title="重新扫描本机" aria-label="重新扫描本机" disabled={busy} onClick={onRefresh}>
          ↻
        </button>
      </header>

      <div className="rows-scroll">
        {state.status === 'loading' ? <ListSkeleton rows={9} /> : null}

        {state.status === 'error' ? <ErrorState message={state.error} onRetry={onRefresh} /> : null}

        {state.status === 'ready' && state.data.items.length === 0 ? (
          hasFilters ? (
            <EmptyState
              title="没有匹配的 skill"
              hint="当前筛选条件下没有任何结果。"
              actionLabel="清空筛选"
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
                onFavorite={onFavorite}
                healthLabels={healthLabels}
                onOpen={onOpenSkill}
              />
            ))}
          </ul>
        ) : null}
      </div>

      {state.status === 'ready' && state.data.items.length > 0 ? (
        <Pagination page={page} pageSize={pageSize} total={state.data.total} onPageChange={onPageChange} />
      ) : null}
    </section>
  );
}
