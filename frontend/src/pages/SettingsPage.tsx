import { useState } from 'react';
import { TranslationSettings } from '../components/TranslationSettings';
import { RepositoryInstall } from '../components/RepositoryInstall';
import { ProjectSettings } from '../components/ProjectSettings';
import type { Health, RootsResponse, UpstreamQuota } from '../api/types';
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
  section: string;
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

function UpstreamQuotaBlock() {
  const { state: quota, reload: onRetry } = useApi<UpstreamQuota>(signal => api.upstreamQuota(signal), []);
  if (quota.status === 'loading') {
    return <TableSkeleton rows={2} />;
  }
  if (quota.status === 'error') {
    return <ErrorState title="GitHub 额度读取失败" message={quota.error} onRetry={onRetry} />;
  }
  const data = quota.data;
  if (!data.available) {
    return (
      <p className="block-note">
        无法读取 GitHub 额度：{data.detail ?? '未知错误'}（检查是否配置了代理或网络不通）
      </p>
    );
  }
  const reset = data.reset ? new Date(data.reset * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '未知';
  return (
    <>
      <table className="table table--kv">
        <tbody>
          <tr>
            <th scope="row">凭据</th>
            <td className="mono">
              {data.mode === 'token'
                ? `GitHub token（来源：${data.source === 'env' ? '环境变量' : data.source === 'config' ? 'upstream.json' : '本机 gh CLI'}）`
                : '匿名访问'}
            </td>
          </tr>
          <tr>
            <th scope="row">剩余额度</th>
            <td className="mono">
              {formatCount(data.remaining ?? 0)} / {formatCount(data.limit ?? 0)} · 每小时
            </td>
          </tr>
          <tr>
            <th scope="row">重置时间</th>
            <td className="mono">{reset}</td>
          </tr>
        </tbody>
      </table>
      <p className="block-note">
        {data.mode === 'token'
          ? '已使用 token，单次版本检查成本很低（同仓库 skill 共享一次请求）。'
          : '匿名每小时只有 60 次，检查整个库会很快用完。配置 token 可提升到每小时 5000 次：设置环境变量 SKILLDESK_GITHUB_TOKEN，或写 ~/.config/skilldesk/upstream.json 的 {"githubToken": "..."}（本机已登录 gh 时也会自动复用）。'}
      </p>
    </>
  );
}

export function SettingsPage({ health, onRetryHealth, section }: SettingsPageProps) {
  const roots = useApi<RootsResponse>((signal) => api.roots(signal), []);
  const [showQuota, setShowQuota] = useState(false);
  const [projectGeneration, setProjectGeneration] = useState(0);

  return (
    <div className="page">
      <PageHeader title="设置" sub="管理本机扫描范围，以及功能分类和翻译使用的 AI 服务。" />

      <ProjectSettings key={'projects-' + section} focus={section === 'projects'} onChange={() => { setProjectGeneration(n => n + 1); roots.reload(); onRetryHealth(); }} />
      <RepositoryInstall key={'install-' + section} startOpen={section === 'install'} generation={projectGeneration} onChange={() => { roots.reload(); onRetryHealth(); }} />
      <TranslationSettings />
      <section className="block">
        <h2 className="block-title">宿主根</h2>
        <HostRootsTable roots={roots.state} onRetry={roots.reload} />
      </section>

      <section className="block">
        <h2 className="block-title">GitHub 检查</h2>
        {showQuota ? <UpstreamQuotaBlock /> :
          <button type="button" className="button" onClick={() => setShowQuota(true)}>查询 GitHub 额度</button>}
      </section>

      <section className="block">
        <h2 className="block-title">索引</h2>
        <IndexTable health={health} onRetry={onRetryHealth} />
      </section>

    </div>
  );
}
