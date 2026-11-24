import { useEffect, useMemo, useRef } from 'react';
import { resolveAssetSources } from '../lib/html';

export interface DocumentTarget { rel: string; anchor?: string; raw?: boolean }
interface Props {
  html: string; identityKey: string; file?: string; anchor?: string;
  onFile: (target: DocumentTarget) => void;
}

function revealHeading(root: HTMLElement | null, anchor: string) {
  const slug = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}_\-\s]/gu, '').trim().replace(/\s+/g, '-');
  const headings = root?.querySelectorAll('h1,h2,h3,h4,h5,h6') ?? [];
  Array.from(headings).find(h => slug(h.textContent || '') === slug(anchor))?.scrollIntoView({ block: 'start' });
}

export function SkillBody({ html, identityKey, file = 'SKILL.md', anchor, onFile }: Props) {
  const rendered = useMemo(() => resolveAssetSources(html, identityKey, file), [html, identityKey, file]);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => { if (anchor) revealHeading(root.current, anchor); }, [anchor, rendered]);
  return <div ref={root} className="prose" onClick={event => {
    if (!(event.target instanceof Element)) return;
    const link = event.target.closest<HTMLAnchorElement>('a[data-file]');
    if (!link?.dataset.file) return;
    event.preventDefault();
    if (link.dataset.file === file && link.dataset.anchor) revealHeading(root.current, link.dataset.anchor);
    else onFile({ rel: link.dataset.file, anchor: link.dataset.anchor });
  }} dangerouslySetInnerHTML={{ __html: rendered }} />;
}
