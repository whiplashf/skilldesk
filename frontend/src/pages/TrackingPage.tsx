import type { Health, IssuesResponse } from '../api/types';
import { api } from '../api/endpoints';
import { formatCount } from '../lib/format';
import { ISSUE_KIND_ORDER, severityLabel, severityTone } from '../lib/labels';
import type { AsyncState } from '../lib/useApi';
import { useApi } from '../lib/useApi';
import { Badge } from '../components/Badge';
import { ErrorState } from '../components/ErrorState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';

export interface TrackingPageProps {
  health: AsyncState<Health>;
  onRetryHealth: () => void;
  onOpenSkill: (identityKey: string) => void;
}

interface StatProps {
  value: number | null;
  label: string;
}

function Stat({ value, label }: StatProps) {
  return (
    <div className="stat">
      {value === null ? <Skeleton width="48px" height={22} /> : <span className="stat-value mono">{formatCount(value)}</span>}
      <span className="stat-label">{label}</span>
    </div>
  );
}

export function TrackingPage({ health, onRetryHealth, onOpenSkill }: TrackingPageProps) {
  const issues = useApi<IssuesResponse>((signal) => api.issues(signal), []);
  const counts = health.status === 'ready' ? health.data.counts : null;

  const issueItems = issues.state.status === 'ready' ? issues.state.data.items : [];
  const kindMeta = issues.state.status === 'ready' ? issues.state.data.kinds : {};
  const truncated = counts !== null && issues.state.status === 'ready' && counts.issues > issueItems.length;

  const refresh = () => {
    issues.reload();
    onRetryHealth();
  };

  return (
    <div className="page">
      <PageHeader
        title="跟踪 · 安装健康"
        sub="本机副本的结构性问题：悬空软链、缺失来源、重复实体。上游漂移（drift）检测在 M4 到来，本页只覆盖安装健康。"
        aside={
          <button type="button" className="button button--ghost" onClick={refresh}>
            刷新
          </button>
        }
      />

      {health.status === 'error' ? (
        <ErrorState title="索引状态加载失败" message={health.error} onRetry={onRetryHealth} />
      ) : (
        <>
          <section className="stats" aria-label="索引统计">
            <Stat value={counts?.skills ?? null} label="skill 实体" />
            <Stat value={counts?.placements ?? null} label="落点" />
            <Stat value={counts?.issues ?? null} label="待处理问题" />
          </section>
          {counts === null ? null : (
            <p className="page-note mono">
              悬空软链 {formatCount(counts.dangling)} · 待认领 {formatCount(counts.unclaimed)} · 宿主根{' '}
              {formatCount(counts.roots)}
            </p>
          )}
        </>
      )}

      {issues.state.status === 'loading' ? (
        <div className="issue-groups" aria-hidden="true">
          <Skeleton width="180px" height={13} />
          <Skeleton width="320px" height={10} />
          <Skeleton width="260px" height={10} />
        </div>
      ) : null}

      {issues.state.status === 'error' ? (
        <ErrorState title="问题清单加载失败" message={issues.state.error} onRetry={issues.reload} />
      ) : null}

      {issues.state.status === 'ready' ? (
        <div className="issue-groups">
          {ISSUE_KIND_ORDER.map((kind) => {
            const meta = kindMeta[kind];
            const rows = issueItems.filter((item) => item.kind === kind);
            const label = meta?.label ?? kind;
            return (
              <section className="issue-group" key={kind} aria-label={label}>
                <header className="issue-group-head">
                  <h2 className="issue-group-title">{label}</h2>
                  {meta === undefined ? null : (
                    <Badge tone={severityTone(meta.severity)}>{severityLabel(meta.severity)}</Badge>
                  )}
                  <span className="issue-group-count mono">{formatCount(rows.length)}</span>
                  {meta === undefined ? null : <span className="issue-group-desc">{meta.description}</span>}
                </header>

                {rows.length === 0 ? (
                  <p className="issue-group-empty">没有此类问题。</p>
                ) : (
                  <ul className="issue-rows">
                    {rows.map((issue) => {
                      const body = (
                        <>
                          <span className="issue-detail">{issue.detail}</span>
                          <span className="issue-target mono">{issue.target}</span>
                          {issue.fixable ? (
                            <span className="chip chip--warn" title="M1 只读，暂不提供修复动作">
                              可修复
                            </span>
                          ) : null}
                        </>
                      );

                      return (
                        <li key={issue.id}>
                          {kind === 'unclaimed_source' && issue.identity_key !== '' ? (
                            <button
                              type="button"
                              className="issue-row issue-row--link"
                              title="打开该 skill 详情"
                              onClick={() => {
                                onOpenSkill(issue.identity_key);
                              }}
                            >
                              {body}
                              <span className="issue-arrow" aria-hidden="true">
                                →
                              </span>
                            </button>
                          ) : (
                            <div className="issue-row">{body}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            );
          })}
          {truncated ? <p className="page-note">问题总数超过 500 条，列表只显示前 500 条。</p> : null}
          <p className="page-note">健康问题在 M1 只读展示；批量修复与认领动作随可写里程碑开放。</p>
        </div>
      ) : null}
    </div>
  );
}
