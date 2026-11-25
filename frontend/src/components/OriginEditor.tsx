import { useEffect, useState } from 'react';
import type { AssetChanges, SkillSummary } from '../api/types';

export type Save = (item: SkillSummary, changes: AssetChanges) => Promise<boolean>;

export function OriginEditor({ data, save, busy }: { data: SkillSummary; save: Save; busy: boolean }) {
  const [editing, setEditing] = useState<SkillSummary | null>(null);
  const [repo, setRepo] = useState('');
  const [path, setPath] = useState('');
  const [mine, setMine] = useState(data.mine);
  useEffect(() => setMine(data.mine), [data.mine]);
  const canClaim = !data.upstream && ['none', 'claimed'].includes(data.provenance.confidence);
  async function changeMine(selected: boolean) {
    setMine(selected);
    if (!await save(data, { mine: selected })) setMine(data.mine);
  }
  return <div className="origin-editor">
    {canClaim ? <label className="check-field"><input type="checkbox" checked={mine} disabled={busy}
      onChange={event => void changeMine(event.target.checked)} /> 我写的</label>
      : mine && <button type="button" className="link-button" disabled={busy}
        onClick={() => void changeMine(false)}>移除自写标记</button>}
    {editing ? <form className="settings-form" onSubmit={async event => {
      event.preventDefault();
      if (await save(editing, { github: { repo, path } })) setEditing(null);
    }}>
      <label>GitHub 仓库<input required placeholder="owner/repo" value={repo} onChange={e => setRepo(e.target.value)} /></label>
      <label>仓库内路径<input required placeholder="skills/example/SKILL.md" value={path} onChange={e => setPath(e.target.value)} /></label>
      <div className="form-actions"><button className="button" disabled={busy}>保存来源</button>
        <button type="button" className="button" onClick={() => setEditing(null)}>取消</button>
        {editing.hasTrackingOverride && <button type="button" className="link-button" disabled={busy} onClick={async () => {
          if (await save(editing, { github: null })) setEditing(null);
        }}>恢复扫描来源</button>}</div>
    </form> : <button className="button" type="button" onClick={() => {
      setRepo(data.upstream?.repo ?? ''); setPath(data.upstream?.path || 'SKILL.md'); setEditing(data);
    }}>{data.upstream ? '编辑 GitHub 来源' : '关联 GitHub 来源'}</button>}
  </div>;
}
