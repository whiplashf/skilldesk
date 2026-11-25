import type { Provenance } from '../api/types';
import { confidenceTone } from '../lib/labels';
import { Badge } from './Badge';

interface ProvenanceBlockProps {
  provenance: Provenance;
  confidenceLabel: string;
  showScannedSource: boolean;
  showScannedPath: boolean;
}

const EVIDENCE_LABELS: Record<string, string> = {
  lockfile: '安装锁文件', 'git checkout': '本地 Git 仓库', frontmatter: 'SKILL.md 文档头',
};

export function ProvenanceBlock({ provenance, confidenceLabel, showScannedSource, showScannedPath }: ProvenanceBlockProps) {
  const { confidence, evidence, localRoot, path, ref, sourceLabel } = provenance;
  const hasEvidence = evidence && evidence !== '我写的';
  if (!hasEvidence && !localRoot && !ref && !(showScannedPath && path) && !showScannedSource) return null;
  return <dl className="block kv">
    {showScannedSource && <div className="kv-row"><dt>扫描来源</dt><dd className="mono break">{sourceLabel}</dd></div>}
    {hasEvidence && <div className="kv-row"><dt>来源依据</dt>
      <dd className="kv-inline"><Badge tone={confidenceTone(confidence)}>{confidenceLabel}</Badge>
        <span>{EVIDENCE_LABELS[evidence] ?? evidence}</span></dd></div>}
    {showScannedPath && path && <div className="kv-row"><dt>仓库内路径</dt><dd className="mono break">{path}</dd></div>}
    {ref && <div className="kv-row"><dt>记录的版本</dt><dd className="mono break">{ref}</dd></div>}
    {localRoot && <div className="kv-row"><dt>本地仓库</dt><dd className="mono break">{localRoot}</dd></div>}
  </dl>;
}
