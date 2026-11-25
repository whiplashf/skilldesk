import { useEffect, useState } from 'react';
import type { AssetChanges, SkillSummary } from '../api/types';

export type Save = (item: SkillSummary, changes: AssetChanges) => Promise<boolean>;

export function OriginEditor({ data, save, busy }: { data: SkillSummary; save: Save; busy: boolean }) {
  const [editing, setEditing] = useState(false);
  const [repo, setRepo] = useState('');
  const [path, setPath] = useState('');
  const [mine, setMine] = useState(data.mine);
  useEffect(() => setMine(data.mine), [data.mine]);
  return <div className="origin-editor">
    <label className="check-field"><input type="checkbox" checked={mine} disabled={busy}
      onChange={async event => {
        const selected = event.target.checked;
        setMine(selected);
        if (!await save(data, { mine: selected })) setMine(data.mine);
      }} /> 我写的</label>
    {data.hasTrackingOverride && data.upstream && <p className="source-coordinate">跟踪来源 · {data.upstream.repo} / {data.upstream.path}</p>}
    {editing ? <form className="settings-form" onSubmit={async event => {
      event.preventDefault();
      if (await save(data, { github: { repo, path } })) setEditing(false);
    }}>
      <label>GitHub 仓库<input required placeholder="owner/repo" value={repo} onChange={e => setRepo(e.target.value)} /></label>
      <label>仓库内路径<input required placeholder="skills/example/SKILL.md" value={path} onChange={e => setPath(e.target.value)} /></label>
      <div className="form-actions"><button className="button" disabled={busy}>保存来源</button>
        <button type="button" className="button" onClick={() => setEditing(false)}>取消</button>
        {data.hasTrackingOverride && <button type="button" className="link-button" disabled={busy} onClick={async () => {
          if (await save(data, { github: null })) setEditing(false);
        }}>恢复扫描来源</button>}</div>
    </form> : <button className="button" type="button" onClick={() => {
      setRepo(data.upstream?.repo ?? ''); setPath(data.upstream?.path || 'SKILL.md'); setEditing(true);
    }}>{data.upstream ? '编辑 GitHub 来源' : '关联 GitHub 来源'}</button>}
  </div>;
}
