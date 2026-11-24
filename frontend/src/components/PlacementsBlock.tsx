import type { Placement } from '../api/types';
import { hostKindLabel } from '../lib/labels';
import { Badge } from './Badge';

export interface PlacementsBlockProps {
  placements: Placement[];
}

export function PlacementsBlock({ placements }: PlacementsBlockProps) {
  return (
    <section className="block">
      <h3 className="block-title">
        落点 <span className="block-count mono">{placements.length}</span>
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
          </li>
        ))}
      </ul>
    </section>
  );
}
