import { useRef, type ReactNode } from 'react';
import type { RepositoryGroup, SkillSummary } from '../api/types';
import { Pagination } from './Pagination';

interface Props {
  groups: RepositoryGroup[];
  items: SkillSummary[];
  pages: Record<string, number>;
  pageSize: number;
  onPage: (key: string, page: number) => void;
  renderRows: (items: SkillSummary[]) => ReactNode;
}

export function SourceGroups({ groups, items, pages, pageSize, onPage, renderRows }: Props) {
  const lastOpenPage = useRef(new Map<string, number>());
  const members = new Map<string, SkillSummary[]>();
  for (const item of items) {
    const key = item.repository.key;
    const group = members.get(key);
    if (group) group.push(item);
    else members.set(key, [item]);
  }
  return <div className="source-groups">{groups.map(group => {
    const id = 'source-members-' + encodeURIComponent(group.key);
    const lastPage = Math.ceil(group.count / pageSize);
    const page = Math.min(pages[group.key] ?? group.page ?? 0, lastPage);
    const open = page > 0;
    const ready = page === group.page;
    return <section className="source-group" key={group.key}>
      <h3><button type="button" className="source-heading" id={id + '-heading'} aria-expanded={open} aria-controls={id}
        onClick={() => {
          if (open) lastOpenPage.current.set(group.key, page);
          onPage(group.key, open ? 0 : Math.min(lastOpenPage.current.get(group.key) || 1, lastPage));
        }}>
        <i className="source-chevron" aria-hidden="true" /><i className="folder-icon" aria-hidden="true" />
        <span className="source-name">{group.name}
          {group.location && group.location !== 'github.com' && <small title={group.location}>{group.location}</small>}
        </span>
        <span className="source-count" aria-label={group.count + ' 个 skill'}>{group.count}</span>
      </button></h3>
      <div id={id} hidden={!open} aria-busy={open && !ready}>
        {open && (ready ? renderRows(members.get(group.key) ?? []) : <p className="source-loading" role="status">正在读取技能…</p>)}
        {open && ready && group.count > pageSize && <Pagination page={page - 1} pageSize={pageSize} total={group.count}
          onPageChange={next => {
            onPage(group.key, next + 1);
            const heading = document.getElementById(id + '-heading');
            heading?.focus({ preventScroll: true });
            heading?.closest('section')?.scrollIntoView({ block: 'start' });
          }} />}
      </div>
    </section>;
  })}</div>;
}
