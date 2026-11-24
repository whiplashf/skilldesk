import type { Provenance } from '../api/types';
import { confidenceTone } from '../lib/labels';
import { Badge } from './Badge';

export interface ProvenanceBlockProps {
  provenance: Provenance;
  /** Server-rendered label for the detail payload (falls back to the local map). */
  confidenceLabel: string;
}

export function ProvenanceBlock({ provenance, confidenceLabel }: ProvenanceBlockProps) {
  const claimed = provenance.label !== '';

  return (
    <section className="block">
      <h3 className="block-title">来源</h3>
      <dl className="kv">
        <div className="kv-row">
          <dt>来源</dt>
          <dd>{claimed ? <span className="mono break">{provenance.label}</span> : <span className="dim">未认领</span>}</dd>
        </div>
        <div className="kv-row">
          <dt>可信度</dt>
          <dd className="kv-inline">
            <Badge tone={confidenceTone(provenance.confidence)}>{confidenceLabel}</Badge>
            {provenance.evidence === '' ? null : <span className="dim mono">依据 {provenance.evidence}</span>}
          </dd>
        </div>
        {provenance.path === '' ? null : (
          <div className="kv-row">
            <dt>路径</dt>
            <dd className="mono break">{provenance.path}</dd>
          </div>
        )}
        {provenance.ref === '' ? null : (
          <div className="kv-row">
            <dt>ref</dt>
            <dd className="mono break">{provenance.ref}</dd>
          </div>
        )}
      </dl>
      {claimed ? null : <p className="block-note">没有任何机器记录能确定来源，暂按待认领处理。</p>}
    </section>
  );
}
