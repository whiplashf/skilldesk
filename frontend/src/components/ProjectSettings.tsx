import { useEffect, useRef, useState } from 'react';
import { describeError } from '../api/client';
import { api } from '../api/endpoints';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';

export function ProjectSettings({ onChange, focus }: { onChange: () => void; focus: boolean }) {
  const projects = useApi(api.projects, [], true);
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (focus) input.current?.focus(); }, [focus]);

  async function change(folder: string, remove = false) {
    setBusy(true);
    setMessage('');
    try {
      await api.changeProject(folder, remove);
      if (!remove) setPath('');
      setMessage(remove ? '已移出扫描范围' : '项目已加入扫描范围');
      projects.reload();
      onChange();
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return <section className="block">
    <h2 className="block-title">项目目录</h2>
    <p className="block-note">将项目加入扫描范围，即可在技能库查看它的技能。</p>
    {projects.state.status === 'error' && <ErrorState message={projects.state.error} onRetry={projects.reload} />}
    {projects.state.status === 'ready' && <ul className="project-paths">
      {projects.state.data.effective.map(folder => <li key={folder}><code>{folder}</code>
        {projects.state.status === 'ready' && projects.state.data.saved.includes(folder)
          ? <button type="button" className="link-button" disabled={busy} onClick={() => void change(folder, true)}>移出扫描范围</button>
          : <span className="dim">环境变量</span>}
      </li>)}
    </ul>}
    <form className="settings-form" onSubmit={event => { event.preventDefault(); void change(path.trim()); }}>
      <label>项目绝对路径<input ref={input} required value={path} placeholder="/path/to/project" onChange={e => setPath(e.target.value)} /></label>
      <div className="form-actions"><button className="button" disabled={busy || !path.trim()}>添加项目</button>
        <span role="status">{message}</span></div>
    </form>
  </section>;
}
