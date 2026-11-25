import { useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { MaintenancePreview as Plan } from '../api/types';
import { skillHash } from '../lib/route';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { MaintenancePreview } from './MaintenancePreview';

type Props = { onChange: () => void; generation: number; startOpen: boolean };

function InstallForm({ onChange, generation, startOpen }: Props) {
  const roots = useApi(api.installRoots, [generation], true);
  const [selection, setSelection] = useState('');
  const [repo, setRepo] = useState('');
  const [path, setPath] = useState('');
  const [candidates, setCandidates] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Plan>();
  const [installed, setInstalled] = useState<{ name: string; key: string }>();
  const options = roots.state.status === 'ready' ? roots.state.data.items : [];
  const root = options.find(p => p.path === selection)?.path ?? options[0]?.path ?? '';
  async function preview(chosen = path.trim()) {
    setError(''); setInstalled(undefined); setBusy(true);
    try { setPlan(await api.previewInstall(root, repo.trim(), chosen)); }
    catch (err) {
      if (err instanceof ApiError && err.candidates.length) {
        setCandidates(err.candidates); setFilter('');
      } else setError(describeError(err));
    }
    finally { setBusy(false); }
  }
  return <>
    {roots.state.status === 'error' && <ErrorState message={roots.state.error} onRetry={roots.reload} />}
    <form className="settings-form" onSubmit={event => { event.preventDefault(); void preview(); }}>
      <label>仓库地址<input required autoFocus={startOpen} disabled={busy} value={repo} onChange={e => {
        setRepo(e.target.value); setPath(''); setCandidates([]); setError(''); setInstalled(undefined);
      }}
        placeholder="owner/repo 或完整 Git 地址" /></label>
      <details><summary>指定仓库内路径</summary><label>仓库内的文档路径<input disabled={busy} value={path} onChange={e => {
        setPath(e.target.value); setCandidates([]);
      }} placeholder="如 skills/example/SKILL.md" /></label></details>
      <label>安装到<select value={root} disabled={busy || !options.length} onChange={e => setSelection(e.target.value)}>
        {options.map(p => <option key={p.path} value={p.path}>{p.label} · {p.path}</option>)}
      </select></label>
      {!candidates.length && <div className="form-actions"><button className="button" disabled={busy || !repo.trim() || !root}>
        {busy ? '正在读取仓库…' : '预览安装'}</button></div>}
      {roots.state.status === 'ready' && !options.length && <p className="block-note">请先添加一个可写的项目安装目录。</p>}
    </form>
    {candidates.length > 0 && <section className="install-choices"><h3>选择要安装的 skill</h3>
      {candidates.length > 8 && <label>筛选名称或路径 <input type="search" value={filter} onChange={e => setFilter(e.target.value)} /></label>}
      <ul>{candidates.filter(p => p.toLowerCase().includes(filter.toLowerCase())).map(p =>
        <li key={p}><button className="button" type="button" disabled={busy} onClick={() => void preview(p)}>
          <strong>{p.split('/').at(-2) || repo.split('/').at(-1)?.replace(/\.git$/, '')}</strong><small>{p}</small></button></li>)}</ul>
      {!candidates.some(p => p.toLowerCase().includes(filter.toLowerCase())) && <p>没有匹配的路径。</p>}
      {busy && <span role="status">正在准备安装预览…</span>}
    </section>}
    {error && <p className="action-message" role="alert">{error}</p>}
    {installed && <p className="action-message" role="status">已安装 {installed.name} · <a href={skillHash(installed.key)}>在技能库查看</a></p>}
    {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)} onApplied={result => {
      const source = plan.source!;
      setInstalled({ name: result.target.split('/').pop() || result.target,
        key: 'src:' + source.host + '/' + source.repo + '@' + source.path });
      setPlan(undefined); setCandidates([]); onChange();
    }} />}
  </>;
}

export function RepositoryInstall(props: Props) {
  const [open, setOpen] = useState(props.startOpen);
  return <section className="block install-settings">
    <details open={open} onToggle={e => setOpen(e.currentTarget.open)}><summary className="block-title">从仓库安装</summary>
      {open && <InstallForm {...props} />}
    </details>
  </section>;
}
