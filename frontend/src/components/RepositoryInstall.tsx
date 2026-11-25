import { useState } from 'react';
import { describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { MaintenancePreview as Plan } from '../api/types';
import { skillHash } from '../lib/route';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { MaintenancePreview } from './MaintenancePreview';

type Props = { onChange: () => void; generation: number };

function InstallForm({ onChange, generation }: Props) {
  const roots = useApi(api.installRoots, [generation], true);
  const [selection, setSelection] = useState('');
  const [repo, setRepo] = useState('');
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Plan>();
  const [installed, setInstalled] = useState<{ name: string; key: string }>();
  const options = roots.state.status === 'ready' ? roots.state.data.items : [];
  const root = options.find(p => p.path === selection)?.path ?? options[0]?.path ?? '';
  async function preview() {
    setError(''); setInstalled(undefined); setBusy(true);
    try { setPlan(await api.previewInstall(root, repo.trim(), path.trim() || 'SKILL.md')); }
    catch (err) { setError(describeError(err)); }
    finally { setBusy(false); }
  }
  return <>
    {roots.state.status === 'error' && <ErrorState message={roots.state.error} onRetry={roots.reload} />}
    <form className="settings-form" onSubmit={event => { event.preventDefault(); void preview(); }}>
      <label>仓库地址<input required value={repo} onChange={e => setRepo(e.target.value)}
        placeholder="owner/repo 或完整 Git 地址" /></label>
      <label>仓库内的文档路径<input value={path} onChange={e => setPath(e.target.value)}
        placeholder="SKILL.md 或 skills/example/SKILL.md" /></label>
      <label>安装到<select value={root} disabled={!options.length} onChange={e => setSelection(e.target.value)}>
        {options.map(p => <option key={p.path} value={p.path}>{p.label} · {p.path}</option>)}
      </select></label>
      <div className="form-actions"><button className="button" disabled={busy || !repo.trim() || !root}>
        {busy ? '正在读取仓库…' : '预览安装'}</button></div>
      {roots.state.status === 'ready' && !options.length && <p className="block-note">请先添加一个可写的项目安装目录。</p>}
    </form>
    {error && <p className="action-message" role="alert">{error}</p>}
    {installed && <p className="action-message" role="status">已安装 {installed.name} · <a href={skillHash(installed.key)}>在技能库查看</a></p>}
    {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)} onApplied={result => {
      const source = plan.source!;
      setInstalled({ name: result.target.split('/').pop() || result.target,
        key: 'src:' + source.host + '/' + source.repo + '@' + source.path });
      setPlan(undefined); onChange();
    }} />}
  </>;
}

export function RepositoryInstall(props: Props) {
  const [open, setOpen] = useState(false);
  return <section className="block install-settings">
    <details onToggle={e => setOpen(e.currentTarget.open)}><summary className="block-title">从仓库安装</summary>
      {open && <InstallForm {...props} />}
    </details>
  </section>;
}
