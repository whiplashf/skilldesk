import type { Facets } from '../api/types';
import type { FacetAxis, Filters } from '../lib/filters';
import { confidenceLabel, healthLabel, hostKindLabel } from '../lib/labels';
import { sourceHost, sourceTail } from '../lib/format';
import { HASH } from '../lib/route';
import { FacetGroup } from './FacetGroup';
import { FacetRow } from './FacetRow';

const CONFIDENCE_ORDER = ['recorded', 'declared', 'none'] as const;
const HEALTH_ORDER = ['unclaimed_source', 'duplicate_content', 'dangling_link'] as const;

function orderBy(values: ReadonlyArray<string>, order: ReadonlyArray<string>): string[] {
  const known = order.filter((value) => values.includes(value));
  const rest = values.filter((value) => !order.includes(value));
  return [...known, ...rest];
}

export function FacetGroups({
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

      <FacetGroup title="扫描来源" hint="host/repo" scroll>
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
