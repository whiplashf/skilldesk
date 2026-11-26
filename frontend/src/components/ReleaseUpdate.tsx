import { useState } from 'react';
import { api } from '../api/endpoints';
import { describeError } from '../api/client';
import type { GitHubRelease, MaintenancePreview as Plan, MaintenanceResult } from '../api/types';
import { MaintenancePreview } from './MaintenancePreview';

export function ReleaseUpdate({ identityKey, entries, release, onApplied }: {
  identityKey: string; entries: string[]; release: GitHubRelease; onApplied: (result: MaintenanceResult) => void;
}) {
  const [chosen, setChosen] = useState('');
  const entry = entries.includes(chosen) ? chosen : entries[0];
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Plan>();
  async function preview() {
    if (!entry) return;
    setPending(true); setError('');
    try {
      setPlan(await api.previewPlacement(identityKey, entry, 'update', { tag: release.tag, commit: release.commit }));
    } catch (err) { setError(describeError(err)); }
    finally { setPending(false); }
  }
  return <div className="release-action">
    {entries.length > 1 && <label>更新位置 <select value={entry} disabled={pending}
      onChange={e => { setChosen(e.target.value); setError(''); }}>
      {entries.map(path => <option key={path} value={path}>{path}</option>)}</select></label>}
    <button className="button release-update" type="button" disabled={pending || !entry} onClick={() => void preview()}>
      {pending ? '正在准备更新…' : '更新至 ' + release.tag}</button>
    {error && <p role="alert" className="action-message">{error}</p>}
    {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)}
      onApplied={result => { setPlan(undefined); onApplied(result); }} />}
  </div>;
}
