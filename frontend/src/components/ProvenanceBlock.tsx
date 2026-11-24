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
          <dt>上游来源</dt>
          <dd>{claimed ? <span className="mono break">{provenance.label}</span> : <span className="dim">未认领</span>}</dd>
        </div>
        {provenance.localRoot && <div className="kv-row">
          <dt>本地仓库</dt>
          <dd className="mono break">{provenance.localRoot}</dd>
        </div>}
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
      {claimed ? null : <p className="block-note">可以在上方关联 GitHub 仓库和文档路径，以便检查版本。</p>}
    </section>
  );
}
