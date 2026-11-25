import { useState } from 'react';
import type { AssetChanges, Issue, MaintenancePreview as Plan, SkillSummary } from '../api/types';
import { api } from '../api/endpoints';
import { describeError } from '../api/client';
import { hostKindLabel, ISSUE_KIND_ORDER, severityLabel, severityTone } from '../lib/labels';
import { useApi } from '../lib/useApi';
import { Badge } from '../components/Badge';
import { ErrorState } from '../components/ErrorState';
import { PageHeader } from '../components/PageHeader';
import { OriginEditor } from '../components/OriginEditor';
import { MaintenancePreview } from '../components/MaintenancePreview';

function ClaimSource({ issue, onSaved }: { issue: Issue; onSaved: () => void }) {
  const item = useApi(signal => api.skill(issue.identity_key, signal), [issue.identity_key], true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(skill: SkillSummary, changes: AssetChanges) {
    setBusy(true); setError('');
    try { await api.patch(skill, changes); onSaved(); return true; }
    catch (err) { setError(describeError(err)); item.reload(); return false; }
    finally { setBusy(false); }
  }
  return <div className="issue-claim">
    {item.state.status === 'ready' ? <OriginEditor data={item.state.data} save={save} busy={busy} />
      : item.state.status === 'error' ? <ErrorState message={item.state.error} onRetry={item.reload} /> : <p role="status">正在读取来源…</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function TrackingPage({ generation, onScanned, onOpenSkill }: {
  generation: string; onScanned: () => void; onOpenSkill: (key: string) => void;
}) {
  const issues = useApi(api.issues, [generation], true);
  const [editing, setEditing] = useState('');
  const [busy, setBusy] = useState('');
  const [plan, setPlan] = useState<Plan>();
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const data = issues.state.data;
  function refreshView() { issues.reload(); onScanned(); }
  async function refresh() {
    setBusy('refresh'); setError(''); setMessage('');
    try { await api.rescan(); refreshView(); setMessage('已重新扫描本机'); }
    catch (err) { setError(describeError(err)); }
    finally { setBusy(''); }
  }
  async function preview(issue: Issue) {
    setBusy(issue.id); setError(''); setMessage('');
    try { setPlan(await api.previewDangling(issue.location)); }
    catch (err) { setError(describeError(err)); issues.reload(); }
    finally { setBusy(''); }
  }
  return <div className="page health-page">
    <PageHeader title="安装健康" sub="检查本机的失效入口、待确认来源和重复副本。"
      aside={<button type="button" className="button" disabled={Boolean(busy)} onClick={() => void refresh()}>
        {busy === 'refresh' ? '正在扫描…' : '刷新'}</button>} />
    {error && <p className="action-message" role="alert">{error}</p>}
    {message && <p className="action-message" role="status">{message}</p>}
    {issues.state.status === 'error' && <ErrorState message={issues.state.error} onRetry={issues.reload} />}
    {!data && issues.state.status === 'loading' && <p role="status">正在读取安装健康…</p>}
    {data && <>
      <section className="stats" aria-label="安装统计">
        {[[data.counts.skills, '个本机 skill'], [data.counts.placements, '个安装位置'], [data.counts.issues, '项待处理']].map(([n, label]) =>
          <div className="stat" key={label}><span className="stat-value mono">{n}</span><span className="stat-label">{label}</span></div>)}
      </section>
      {data.total === 0 && <div className="state"><h2 className="state-title">安装状态良好</h2><p>本次扫描没有发现需要处理的问题。</p></div>}
      {ISSUE_KIND_ORDER.map(kind => {
        const rows = data.items.filter(i => i.kind === kind);
        const meta = data.kinds[kind];
        if (!rows.length || !meta) return null;
        return <section className="issue-group" key={kind} aria-label={meta.label}>
          <header className="issue-group-head"><h2 className="issue-group-title">{meta.label}</h2>
            <span className="issue-group-count mono">{rows.length}</span><Badge tone={severityTone(meta.severity)}>{severityLabel(meta.severity)}</Badge></header>
          <ul className="issue-rows">{rows.map(issue => <li key={issue.id}>
            <div className="issue-row"><div className="issue-description">
              <strong>{issue.name}</strong><span>{issue.agents.map(hostKindLabel).join('、')}</span>
              <p>{kind === 'dangling_link' ? '此入口指向的文件或目录已不存在。' : kind === 'unclaimed_source'
                ? '本机尚无来源记录。' : issue.detail}</p>
              <details><summary>查看位置</summary><code>{issue.location}</code>
                {issue.missingTarget && <p>原目标 <code>{issue.missingTarget}</code></p>}</details>
            </div>
            {kind === 'unclaimed_source' ? <button type="button" className="button" aria-expanded={editing === issue.id}
              onClick={() => setEditing(editing === issue.id ? '' : issue.id)}>{editing === issue.id ? '收起' : '确认来源'}</button>
              : kind === 'dangling_link' ? issue.fixable
                ? <button type="button" className="button" disabled={Boolean(busy)} onClick={() => void preview(issue)}>
                  {busy === issue.id ? '正在准备…' : '预览解除失效链接'}</button>
                : <small>请在对应的 Agent 或源码仓库中检查此入口。</small>
              : <button type="button" className="button" onClick={() => onOpenSkill(issue.identity_key)}>查看副本</button>}
            </div>
            {editing === issue.id && <ClaimSource issue={issue} onSaved={() => {
              setEditing(''); setMessage('已确认 ' + issue.name + ' 的来源'); refreshView();
            }} />}
          </li>)}</ul>
        </section>;
      })}
      {data.total > data.items.length && <p className="block-note">显示前 {data.items.length} 项，共 {data.total} 项。</p>}
    </>}
    {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)} onApplied={result => {
      setPlan(undefined); setMessage('已解除失效链接 · ' + result.target); refreshView();
    }} />}
  </div>;
}
