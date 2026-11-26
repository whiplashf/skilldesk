import type { SkillSummary } from '../api/types';
import { accessSummary, healthLabel, VERSION_LABELS } from '../lib/labels';

interface Props {
  item: SkillSummary;
  index: number;
  selected: boolean;
  busy: boolean;
  grouped: boolean;
  showCategory: boolean;
  healthLabels: Record<string, string>;
  onOpen: (key: string) => void;
  onFavorite: (item: SkillSummary) => void;
}

export function SkillRow({ item, index, selected, busy, grouped, showCategory, healthLabels, onOpen, onFavorite }: Props) {
  const version = item.versionStatus;
  const status = version ? VERSION_LABELS[version.status] : grouped ? '' : item.mine ? '我写的'
    : item.upstream ? 'GitHub' : item.provenance.sourceLabel || '待确认来源';
  return (
    <li className={selected ? 'skill-entry is-current' : 'skill-entry'}>
      <button type="button" className="row" data-row-index={index} data-skill-key={item.identity_key} aria-current={selected || undefined}
        onClick={() => onOpen(item.identity_key)}>
        <span className="row-top"><strong className="row-name">{item.name}</strong>{status && <span className="row-status">{status}</span>}</span>
        <span className="row-desc">{item.description || '无描述'}</span>
        <span className="row-foot">
          {showCategory && item.category.key !== 'pending' && <span className="row-category">{item.category.name}</span>}
          {accessSummary(item.access)}
        </span>
        {item.health.filter(kind => kind !== 'unclaimed_source').map(kind =>
          <span className="row-issue" key={kind}>{healthLabel(kind, healthLabels)}</span>)}
      </button>
      <button type="button" className="row-star" aria-label={(item.favorite ? '取消收藏 ' : '收藏 ') + item.name}
        aria-pressed={item.favorite} disabled={busy} onClick={() => onFavorite(item)}>{item.favorite ? '★' : '☆'}</button>
    </li>
  );
}
