import type { Health, RootsResponse } from '../api/types';
import { api } from '../api/endpoints';
import { formatCount, formatDateTime, formatRelative, toIsoString } from '../lib/format';
import { hostKindLabel } from '../lib/labels';
import type { AsyncState } from '../lib/useApi';
import { useApi } from '../lib/useApi';
import { Badge } from '../components/Badge';
import { ErrorState } from '../components/ErrorState';
import { PageHeader } from '../components/PageHeader';
import { TableSkeleton } from '../components/Skeleton';

export interface SettingsPageProps {
  health: AsyncState<Health>;
  onRetryHealth: () => void;
}

function HostRootsTable({ roots, onRetry }: { roots: AsyncState<RootsResponse>; onRetry: () => void }) {
  if (roots.status === 'loading') {
    return <TableSkeleton rows={5} />;
  }
  if (roots.status === 'error') {
    return <ErrorState title="宿主根加载失败" message={roots.error} onRetry={onRetry} />;
  }

  const existing = roots.data.items.filter((root) => root.exists).length;

  return (
    <>
      <p className="block-note mono">
        共 {formatCount(roots.data.items.length)} 个宿主根 · {formatCount(existing)} 个已创建
      </p>
      <table className="table table--hosts">
        <thead>
          <tr>
            <th scope="col">类型</th>
            <th scope="col" className="num">
              条目
            </th>
            <th scope="col">路径</th>
            <th scope="col">状态</th>
          </tr>
        </thead>
        <tbody>
          {roots.data.items.map((root) => (
            <tr key={root.path}>
              <td className="mono nowrap" title={root.label}>
                {hostKindLabel(root.kind)}
              </td>
              <td className="mono num">{formatCount(root.entries)}</td>
              <td className="mono break">{root.path}</td>
              <td>
                {root.exists ? <Badge tone="ok">可用</Badge> : <Badge tone="muted">未创建</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function IndexTable({ health, onRetry }: { health: AsyncState<Health>; onRetry: () => void }) {
  if (health.status === 'loading') {
    return <TableSkeleton rows={4} />;
  }
  if (health.status === 'error') {
    return <ErrorState title="索引信息加载失败" message={health.error} onRetry={onRetry} />;
  }

  const { meta, counts } = health.data;

  return (
    <table className="table table--kv">
      <tbody>
        <tr>
          <th scope="row">上次扫描</th>
          <td>
            <time title={formatRelative(meta.scanned_at)} dateTime={toIsoString(meta.scanned_at)}>
              {formatDateTime(meta.scanned_at)}
            </time>
            <span className="dim"> · {formatRelative(meta.scanned_at)}</span>
          </td>
        </tr>
        <tr>
          <th scope="row">索引 schema</th>
          <td className="mono">{meta.schema}</td>
        </tr>
        <tr>
          <th scope="row">版本</th>
          <td className="mono">{meta.version}</td>
        </tr>
        <tr>
          <th scope="row">lockfile 条目</th>
          <td className="mono">{formatCount(Number(meta.lockfile_entries) || 0)}</td>
        </tr>
        <tr>
          <th scope="row">skill 实体</th>
          <td className="mono">{formatCount(counts.skills)}</td>
        </tr>
        <tr>
          <th scope="row">落点</th>
          <td className="mono">{formatCount(counts.placements)}</td>
        </tr>
        <tr>
          <th scope="row">问题</th>
          <td className="mono">{formatCount(counts.issues)}</td>
        </tr>
      </tbody>
    </table>
  );
}

export function SettingsPage({ health, onRetryHealth }: SettingsPageProps) {
  const roots = useApi<RootsResponse>((signal) => api.roots(signal), []);

  return (
    <div className="page">
      <PageHeader title="设置" sub="M1 只读：宿主根与索引信息仅展示，不提供任何编辑动作。" />

      <section className="block">
        <h2 className="block-title">宿主根</h2>
        <HostRootsTable roots={roots.state} onRetry={roots.reload} />
      </section>

      <section className="block">
        <h2 className="block-title">索引</h2>
        <IndexTable health={health} onRetry={onRetryHealth} />
      </section>

      <section className="block">
        <h2 className="block-title">用户库</h2>
        <p className="block-note">
          M2 将在这里管理用户库：收藏、标签、集合、来源纠正与导入导出。这些改动写入独立的 library.json，不会动
          skill 内容文件。
        </p>
      </section>

      <section className="block">
        <h2 className="block-title">关于</h2>
        <p className="block-note">
          skilldesk 是本地优先的 agent skill 管理器。本页面只读取本机索引；写操作要等可写里程碑开放，届时会带显式确认与
          dry-run。
        </p>
      </section>
    </div>
  );
}
