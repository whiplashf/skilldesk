import { useMemo } from 'react';
import type { SkillDetail as SkillDetailData } from '../api/types';
import { api } from '../api/endpoints';
import { formatBytes, formatCount, formatDateTime, toIsoString } from '../lib/format';
import { confidenceTone, healthLabel, healthTone } from '../lib/labels';
import { HASH } from '../lib/route';
import { resolveAssetSources } from '../lib/html';
import { useApi } from '../lib/useApi';
import { Badge } from './Badge';
import { DetailSkeleton } from './Skeleton';
import { ErrorState } from './ErrorState';
import { PlacementsBlock } from './PlacementsBlock';
import { ProvenanceBlock } from './ProvenanceBlock';
import { SupportFiles } from './SupportFiles';

function SkillBody({ html, identityKey }: { html: string; identityKey: string }) {
  const resolved = useMemo(() => resolveAssetSources(html, identityKey), [html, identityKey]);
  return <div className="prose" dangerouslySetInnerHTML={{ __html: resolved }} />;
}

export interface SkillDetailProps {
  identityKey: string;
  healthLabels: Record<string, string>;
  onOpenFile: (rel: string) => void;
}

export function SkillDetail({ identityKey, healthLabels, onOpenFile }: SkillDetailProps) {
  const detail = useApi<SkillDetailData>((signal) => api.skill(identityKey, signal), [identityKey]);
  const files = useApi((signal) => api.files(identityKey, signal), [identityKey]);

  if (detail.state.status === 'loading') {
    return <DetailSkeleton />;
  }

  if (detail.state.status === 'error') {
    return <ErrorState title="skill 加载失败" message={detail.state.error} onRetry={detail.reload} />;
  }

  const data = detail.state.data;

  return (
    <article className="detail">
      <a className="detail-back" href={HASH.library}>
        ← 列表
      </a>

      <header className="detail-head">
        <div className="detail-title-row">
          <h2 className="detail-name">{data.name}</h2>
          <span className="detail-dir mono">{data.dir_name}</span>
        </div>
        <div className="detail-badges">
          <Badge tone={confidenceTone(data.provenance.confidence)} title="来源可信度">
            {data.confidenceLabel}
          </Badge>
          {data.health.length === 0 ? (
            <Badge tone="ok">无已知问题</Badge>
          ) : (
            data.health.map((kind) => (
              <Badge tone={healthTone(kind)} key={kind}>
                {healthLabel(kind, healthLabels)}
              </Badge>
            ))
          )}
        </div>
        <p className={data.description === '' ? 'detail-desc dim' : 'detail-desc'}>
          {data.description === '' ? '无描述' : data.description}
        </p>
      </header>

      <ProvenanceBlock provenance={data.provenance} confidenceLabel={data.confidenceLabel} />

      <PlacementsBlock placements={data.placements} />

      <section className="block">
        <h3 className="block-title">元数据</h3>
        <dl className="meta-grid">
          <div>
            <dt>体积</dt>
            <dd className="mono">{formatBytes(data.bytes)}</dd>
          </div>
          <div>
            <dt>行数</dt>
            <dd className="mono">{formatCount(data.lines)}</dd>
          </div>
          <div>
            <dt>修改时间</dt>
            <dd>
              <time title={formatDateTime(data.mtime)} dateTime={toIsoString(data.mtime)}>
                {formatDateTime(data.mtime)}
              </time>
            </dd>
          </div>
          <div>
            <dt>落点</dt>
            <dd className="mono">{data.placement_count}</dd>
          </div>
          <div>
            <dt>许可证</dt>
            <dd className={data.license === '' ? 'mono dim' : 'mono'}>{data.license === '' ? '未声明' : data.license}</dd>
          </div>
        </dl>
      </section>

      {data.issues.length === 0 ? null : (
        <section className="block">
          <h3 className="block-title">
            健康问题 <span className="block-count mono">{data.issues.length}</span>
          </h3>
          <ul className="issues">
            {data.issues.map((issue) => (
              <li className="issue" key={issue.id}>
                <Badge tone={healthTone(issue.kind)}>{healthLabel(issue.kind, healthLabels)}</Badge>
                <span className="issue-detail">{issue.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <SupportFiles state={files.state} onOpenFile={onOpenFile} onRetry={files.reload} />

      <section className="block block--body">
        <h3 className="block-title">SKILL.md</h3>
        <SkillBody html={data.html} identityKey={data.identity_key} />
      </section>

      <footer className="detail-foot">
        <span className="detail-foot-label">身份键</span>
        <code className="identity-key" title={data.identity_key}>
          {data.identity_key}
        </code>
      </footer>
    </article>
  );
}
