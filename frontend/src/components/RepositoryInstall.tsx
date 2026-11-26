import { useEffect, useRef, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { MaintenancePreview as Plan } from '../api/types';
import { skillHash } from '../lib/route';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { MaintenancePreview } from './MaintenancePreview';

type Props = { onChange: () => void; generation: number; focus: boolean };

function choiceLabel(path: string): string {
  const folders = path.split('/').slice(0, -1);
  return folders.reverse().find(folder => !/^skills?$/i.test(folder)) ?? folders[0] ?? '仓库根目录';
}

export function RepositoryInstall({ onChange, generation, focus }: Props) {
  const roots = useApi(api.installRoots, [generation], true);
  const [selection, setSelection] = useState('');
  const [repo, setRepo] = useState('');
  const [candidates, setCandidates] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Plan>();
  const [installed, setInstalled] = useState<{ name: string; key: string }>();
  const input = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const options = roots.state.data?.items ?? [];
  const root = options.find(p => p.path === selection) ?? options[0];
  const matches = candidates.filter(path => path.toLowerCase().includes(filter.trim().toLowerCase()));

  useEffect(() => { if (focus) input.current?.focus(); }, [focus]);
  useEffect(() => () => request.current?.abort(), []);

  function cancel() {
    request.current?.abort();
    request.current = null;
    setPending(null);
  }

  async function preview(path = '') {
    if (!root || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setError('');
    setInstalled(undefined);
    setPending(path);
    try {
      const result = await api.previewInstall(root.path, repo.trim(), path, controller.signal);
      if (!controller.signal.aborted) setPlan(result);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.candidates.length) {
        setCandidates(err.candidates);
        setFilter('');
      } else {
        setError(describeError(err));
      }
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPending(null);
      }
    }
  }

  return <section className="repository-install" aria-labelledby="install-title">
    <h2 id="install-title">从仓库安装</h2>
    <p id="install-help">粘贴 GitHub 仓库、目录或 SKILL.md 链接。找到技能后，你可以预览并确认安装。</p>
    <form onSubmit={event => {
      event.preventDefault();
      if (candidates.length) {
        cancel(); setCandidates([]); setError(''); input.current?.focus();
      } else if (repo.trim()) {
        void preview();
      } else {
        setRepo(''); input.current?.focus(); setError('请先粘贴仓库地址。');
      }
    }}>
      <label htmlFor="install-repository">仓库地址</label>
      <div className="repository-entry">
        <input id="install-repository" ref={input} required spellCheck={false} autoCapitalize="none" autoComplete="off"
          aria-describedby="install-help" placeholder="https://github.com/owner/repo" value={repo}
          onChange={e => {
            cancel(); setRepo(e.target.value); setCandidates([]); setFilter(''); setError(''); setInstalled(undefined);
          }} />
        <button type="submit" className="button repository-submit" disabled={!root || pending === ''}
          aria-expanded={candidates.length ? true : undefined} aria-controls={candidates.length ? 'install-choices' : undefined}>
          {candidates.length ? '收起技能列表' : pending === '' ? '正在查找…' : '查找技能'}
        </button>
      </div>
      {root && <div className="install-destination">
        {options.length === 1 ? <><span>安装到</span><strong title={root.path}>{root.label}</strong></> :
          <><label htmlFor="install-root">安装到</label><select id="install-root" value={root.path} title={root.path}
            onChange={e => { cancel(); setSelection(e.target.value); setError(''); setInstalled(undefined); }}>
            {options.map(p => <option key={p.path} value={p.path}>{p.label}
              {options.some(other => other.path !== p.path && other.label === p.label) && ' · ' + p.path}
            </option>)}
          </select></>}
      </div>}
    </form>
    {roots.state.status === 'error' && <ErrorState message={roots.state.error} onRetry={roots.reload} />}
    {roots.state.status === 'ready' && !root && <p>请先<a href="#/settings?section=projects">添加项目目录</a>，以便选择安装位置。</p>}
    {pending !== null && <p className="install-status" role="status">
      {pending ? '正在准备安装预览…' : '正在仓库中查找 SKILL.md…'}
      <button className="link-button" type="button" onClick={cancel}>取消</button>
    </p>}
    {candidates.length > 0 && <section id="install-choices" className="install-choices" aria-labelledby="install-choices-title">
      <h3 id="install-choices-title" aria-live="polite">找到 {candidates.length} 个技能，选择一个预览</h3>
      {candidates.length > 8 && <input aria-label="筛选技能" type="search" placeholder="筛选名称或路径"
        value={filter} onChange={e => setFilter(e.target.value)} />}
      <ul>{matches.map(path => <li key={path}>
        <button className="install-choice" type="button" disabled={pending !== null} onClick={() => void preview(path)}>
          <span><strong>{choiceLabel(path)}</strong><code>{path}</code></span>
          <span aria-hidden="true">›</span>
        </button>
      </li>)}</ul>
      {!matches.length && <p>没有匹配的技能。请试试其他名称或路径。</p>}
    </section>}
    {error && <p className="install-error" role="alert">{error}</p>}
    {installed && <p className="install-status" role="status">已安装 {installed.name}
      <a href={skillHash(installed.key)}>在技能库查看</a></p>}
    {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)} onApplied={result => {
      const source = plan.source!;
      setInstalled({ name: result.target.split('/').pop() || result.target,
        key: 'src:' + source.host + '/' + source.repo + '@' + source.path });
      setPlan(undefined); setCandidates([]); setRepo(''); onChange();
    }} />}
  </section>;
}
