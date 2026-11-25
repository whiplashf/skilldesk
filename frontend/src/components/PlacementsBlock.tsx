import { useState } from 'react';
import { api } from '../api/endpoints';
import { describeError } from '../api/client';
import { actionLabel, MaintenancePreview } from './MaintenancePreview';
import type { MaintenancePreview as Plan, MaintenanceResult, PlacementAction, Placement } from '../api/types';
import { hostKindLabel } from '../lib/labels';
import { Badge } from './Badge';

export interface PlacementsBlockProps {
  placements: Placement[];
  identityKey: string;
  differingCopies: Set<string>;
  onApplied: (result: MaintenanceResult) => void;
}

export function PlacementsBlock({ placements, identityKey, onApplied, differingCopies }: PlacementsBlockProps) {
  const [pending, setPending] = useState('');
  const [plan, setPlan] = useState<Plan>();
  const [error, setError] = useState<{ entry: string; message: string }>();
  async function preview(entry: string, action: PlacementAction) {
    setPending(entry); setError(undefined);
    try { setPlan(await api.previewPlacement(identityKey, entry, action)); }
    catch (err) { setError({ entry, message: describeError(err) }); }
    finally { setPending(''); }
  }
  return (
    <section className="block">
      <h3 className="block-title">
        安装位置 <span className="block-count mono">{placements.length}</span>
      </h3>
      <ul className="placements">
        {placements.map((placement) => (
          <li className="placement" key={`${placement.host_root}\u0000${placement.entry}`}>
            <div className="placement-head">
              <Badge tone="neutral" mono>
                {hostKindLabel(placement.kind)}
              </Badge>
              <span className={placement.is_symlink ? 'placement-kind is-link' : 'placement-kind is-real'}>
                {placement.is_symlink ? '软链' : '实体'}
              </span>
            </div>
            <div className="path mono" title={placement.entry_path}>
              {placement.entry_path}
            </div>
            {placement.is_symlink ? (
              <div className="path path--sub mono" title={placement.realpath}>
                → {placement.realpath}
              </div>
            ) : null}
            {placement.managementNote && <small className="block-note">{placement.managementNote}</small>}
            {placement.actions.length > 0 && <div className="placement-actions">
              {placement.actions.map(action => <button key={action} type="button" className="button"
                disabled={Boolean(pending)} onClick={() => void preview(placement.entry_path, action)}>
                {'预览' + actionLabel[action]}{action === 'update' && differingCopies.has(placement.realpath)
                  ? ' · ' + placement.installedSource?.repo : ''}</button>)}
              {pending === placement.entry_path && <span role="status">正在准备预览…</span>}
            </div>}
            {error?.entry === placement.entry_path && <p className="action-message" role="alert">{error.message}</p>}
          </li>
        ))}
      </ul>
      {plan && <MaintenancePreview plan={plan} onClose={() => setPlan(undefined)}
        onApplied={result => { setPlan(undefined); onApplied(result); }} />}
    </section>
  );
}
