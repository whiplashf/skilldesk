import type { SkillSummary } from '../api/types';

function encodedPath(value: string): string | undefined {
  const segments = value.split('/');
  if (segments.some(segment => !segment || segment === '.' || segment === '..' || segment.includes('\\'))) return;
  return segments.map(encodeURIComponent).join('/');
}

export function SkillSource({ item, trackingDiffers }: { item: SkillSummary; trackingDiffers: boolean }) {
  const { repository, upstream, provenance } = item;
  const coords = upstream?.repo ?? repository.name;
  const [owner = '', name = '', extra] = coords.split('/');
  const project = name.replace(/\.git$/, '');
  const repo = owner + '/' + project;
  const onGitHub = upstream || repository.location === 'github.com';
  const validRepo = [owner, project].every(part => /^[\w.-]+$/.test(part) && part !== '.' && part !== '..');
  const label = provenance.sourceLabel && (provenance.host || repository.key === 'unassigned')
    ? provenance.sourceLabel : repository.name;
  let source = <span title={repository.location}>{label}</span>;
  if (onGitHub && validRepo) {
    const url = 'https://github.com/' + repo;
    const path = upstream && extra === undefined && upstream.path.split('/').pop() === 'SKILL.md' && encodedPath(upstream.path);
    const ref = encodedPath(upstream?.ref || 'HEAD') ?? 'HEAD';
    source = <>
      <span className="source-kind">{trackingDiffers ? 'GitHub 跟踪来源' : upstream ? 'GitHub' : '所在 GitHub 仓库'}</span>
      <a href={url} target="_blank" rel="noopener noreferrer" aria-label={'在 GitHub 打开仓库 ' + repo}>
        {repo}{!path && <span aria-hidden="true"> ↗</span>}</a>
      {upstream && path && <><span aria-hidden="true">/</span>
        <a href={url + '/blob/' + ref + '/' + path} target="_blank" rel="noopener noreferrer"
          title={upstream.path} aria-label={'在 GitHub 查看 ' + upstream.path}>
          {trackingDiffers ? upstream.path : upstream.path.split('/').pop()}<span aria-hidden="true"> ↗</span></a></>}
    </>;
  }
  return <p className="reader-repo"><i className="folder-icon" aria-hidden="true" />{source}</p>;
}
