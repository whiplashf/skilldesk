import type { RefObject } from 'react';
import type { Facets } from '../api/types';
import type { AsyncState } from '../lib/useApi';
import type { FacetAxis, Filters } from '../lib/filters';
import { confidenceLabel, healthLabel, hostKindLabel } from '../lib/labels';
import { sourceHost, sourceTail } from '../lib/format';
import { HASH } from '../lib/route';
import { FacetGroup } from './FacetGroup';
import { FacetRow } from './FacetRow';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';

export interface FilterRailProps {
  search: string;
  onSearchChange: (value: string) => void;
  searchInputRef: RefObject<HTMLInputElement | null>;
  facets: AsyncState<Facets>;
  filters: Filters;
  onToggleFacet: (axis: FacetAxis, value: string) => void;
  onClearFilters: () => void;
  hasFilters: boolean;
  onRetryFacets: () => void;
}

const CONFIDENCE_ORDER = ['recorded', 'declared', 'none'] as const;
const HEALTH_ORDER = ['unclaimed_source', 'duplicate_content', 'dangling_link'] as const;

function orderBy(values: ReadonlyArray<string>, order: ReadonlyArray<string>): string[] {
  const known = order.filter((value) => values.includes(value));
  const rest = values.filter((value) => !order.includes(value));
  return [...known, ...rest];
}

function FacetSkeleton() {
  return (
    <div className="facet-skeleton" aria-hidden="true">
      {[94, 78, 86, 66].map((width) => (
        <Skeleton key={width} width={`${width}%`} height={11} />
      ))}
    </div>
  );
}

function FacetGroups({
  facets,
  filters,
  onToggleFacet,
}: {
  facets: Facets;
  filters: Filters;
  onToggleFacet: (axis: FacetAxis, value: string) => void;
}) {
  const confidenceValues = orderBy(
    facets.confidence.map((facet) => facet.value),
    CONFIDENCE_ORDER,
  );
  const healthValues = orderBy(
    facets.health.map((facet) => facet.value),
    HEALTH_ORDER,
  ).filter((value) => value !== 'dangling_link');

  return (
    <>
      <FacetGroup title="宿主根" hint="agent 目录">
        {facets.hosts.length === 0 ? <p className="facet-empty">无宿主根数据</p> : null}
        {facets.hosts.map((facet) => (
          <FacetRow
            key={`host:${facet.value}`}
            label={hostKindLabel(facet.value)}
            count={facet.count}
            mono
            active={filters.host === facet.value}
            onSelect={() => {
              onToggleFacet('host', facet.value);
            }}
          />
        ))}
      </FacetGroup>

      <FacetGroup title="来源" hint="host/repo" scroll>
        {facets.sources.map((facet) => (
          <FacetRow
            key={`source:${facet.value}`}
            label={sourceTail(facet.value)}
            sub={sourceHost(facet.value)}
            count={facet.count}
            mono
            title={facet.value}
            active={filters.source === facet.value}
            onSelect={() => {
              onToggleFacet('source', facet.value);
            }}
          />
        ))}
        {facets.sources.length === 0 ? <p className="facet-empty">无来源记录</p> : null}
      </FacetGroup>

      <FacetGroup title="可信度">
        {confidenceValues.map((value) => {
          const facet = facets.confidence.find((item) => item.value === value);
          return (
            <FacetRow
              key={`confidence:${value}`}
              label={confidenceLabel(value, facets.confidenceLabels)}
              count={facet?.count ?? 0}
              active={filters.confidence === value}
              onSelect={() => {
                onToggleFacet('confidence', value);
              }}
            />
          );
        })}
      </FacetGroup>

      <FacetGroup title="健康">
        {healthValues.map((value) => {
          const facet = facets.health.find((item) => item.value === value);
          return (
            <FacetRow
              key={`health:${value}`}
              label={healthLabel(value, facets.healthLabels)}
              count={facet?.count ?? 0}
              active={filters.health === value}
              onSelect={() => {
                onToggleFacet('health', value);
              }}
            />
          );
        })}
        <FacetRow
          label={healthLabel('dangling_link', facets.healthLabels)}
          count={facets.health.find((item) => item.value === 'dangling_link')?.count ?? 0}
          href={HASH.tracking}
          title="悬空软链不是 skill，去跟踪页查看"
        />
      </FacetGroup>
    </>
  );
}

export function FilterRail({
  search,
  onSearchChange,
  searchInputRef,
  facets,
  filters,
  onToggleFacet,
  onClearFilters,
  hasFilters,
  onRetryFacets,
}: FilterRailProps) {
  return (
    <aside className="rail" aria-label="筛选">
      <div className="search">
        <input
          ref={searchInputRef}
          type="search"
          className="search-input"
          placeholder="搜索名称或描述"
          aria-label="搜索 skill"
          spellCheck={false}
          autoComplete="off"
          value={search}
          onChange={(event) => {
            onSearchChange(event.target.value);
          }}
        />
        {search === '' ? (
          <kbd className="search-hint" aria-hidden="true">
            /
          </kbd>
        ) : (
          <button
            type="button"
            className="search-clear"
            aria-label="清空搜索"
            onClick={() => {
              onSearchChange('');
            }}
          >
            ×
          </button>
        )}
      </div>

      <FacetGroup title="收藏" hint="M2">
        <FacetRow label="仅收藏" sub="M2 可用" disabled title="收藏在 M2 上线后才可筛选" />
      </FacetGroup>

      {facets.status === 'loading' ? <FacetSkeleton /> : null}
      {facets.status === 'error' ? (
        <ErrorState title="筛选项加载失败" message={facets.error} onRetry={onRetryFacets} />
      ) : null}
      {facets.status === 'ready' ? (
        <FacetGroups facets={facets.data} filters={filters} onToggleFacet={onToggleFacet} />
      ) : null}

      {hasFilters ? (
        <button type="button" className="rail-clear" onClick={onClearFilters}>
          清空筛选
        </button>
      ) : null}
    </aside>
  );
}
