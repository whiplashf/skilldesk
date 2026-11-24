import type { SkillSummary } from '../api/types';
import { sourceTail } from '../lib/format';
import { confidenceLabel, confidenceTone, healthLabel, healthTone, hostKindLabel } from '../lib/labels';
import { Badge } from './Badge';

export interface SkillRowProps {
  item: SkillSummary;
  index: number;
  selected: boolean;
  confidenceLabels: Record<string, string>;
  healthLabels: Record<string, string>;
  onOpen: (identityKey: string) => void;
}

export function SkillRow({ item, index, selected, confidenceLabels, healthLabels, onOpen }: SkillRowProps) {
  const claimed = item.provenance.label !== '';
  const sourceText = claimed ? sourceTail(item.provenance.label) : '—';

  return (
    <li>
      <button
        type="button"
        className={selected ? 'row is-current' : 'row'}
        data-row-index={index}
        aria-current={selected ? 'true' : undefined}
        onClick={() => {
          onOpen(item.identity_key);
        }}
      >
        <span className="row-top">
          <span className="row-name">{item.name}</span>
          <Badge
            tone={confidenceTone(item.provenance.confidence)}
            title={`来源可信度：${confidenceLabel(item.provenance.confidence, confidenceLabels)}`}
          >
            {confidenceLabel(item.provenance.confidence, confidenceLabels)}
          </Badge>
        </span>
        <span className={item.description === '' ? 'row-desc row-desc--empty' : 'row-desc'}>
          {item.description === '' ? '无描述' : item.description}
        </span>
        <span className="row-foot">
          <span
            className={`row-source mono${claimed ? '' : ' is-unclaimed'}`}
            title={claimed ? item.provenance.label : '没有任何机器记录能确定来源'}
          >
            {sourceText}
          </span>
          {item.host_kinds.map((kind) => (
            <span className="chip" key={kind}>
              {hostKindLabel(kind)}
            </span>
          ))}
          {item.health
            .filter((kind) => kind !== 'unclaimed_source')
            .map((kind) => (
              <span className={`chip chip--${healthTone(kind)}`} key={kind}>
                {healthLabel(kind, healthLabels)}
              </span>
            ))}
        </span>
      </button>
    </li>
  );
}
