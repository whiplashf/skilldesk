import { useState, type ReactNode } from 'react';
import type { RepositoryGroup } from '../api/types';

export const libraryViews = [
  { id: 'all', label: '全部' },
  { id: 'github', label: 'GitHub 引入' },
  { id: 'mine', label: '我写的' },
  { id: 'favorites', label: '已收藏' },
] as const;

interface Props {
  children: ReactNode;
  view: string;
  grouped: boolean;
  repositories: RepositoryGroup[];
  active: string;
  loading: boolean;
  onView: (view: string) => void;
  onLayout: (grouped: boolean) => void;
  onRepository: (key: string) => void;
}

export function LibraryNavigation({ children, view, grouped, repositories, active, loading, onView, onLayout, onRepository }: Props) {
  const [expanded, setExpanded] = useState(true);
  const current = repositories.find(repo => repo.key === active);
  return <aside className="library-navigation" aria-label="技能库目录">
    <h2 className="nav-title">技能库</h2>
    <div className="scope-links" role="group" aria-label="查看范围">
      {libraryViews.map(({ id, label }) => <button key={id} type="button" aria-pressed={view === id} onClick={() => onView(id)}>
        <i aria-hidden="true" className={'scope-icon icon-' + id} />{label}
      </button>)}
    </div>
    {children}
    <section className="repository-panel">
      <div className="layout-switch" role="group" aria-label="列表显示方式">
        <button type="button" aria-pressed={grouped} onClick={() => onLayout(true)}>按仓库</button>
        <button type="button" aria-pressed={!grouped} onClick={() => onLayout(false)}>平铺列表</button>
      </div>
      {grouped && <>
        <button type="button" className="directory-toggle" aria-expanded={expanded} aria-controls="repository-directory"
          onClick={() => setExpanded(!expanded)}>
          <span>来源仓库</span><span className="directory-summary">{expanded ? repositories.length : current?.name}</span>
          <i className="chevron" aria-hidden="true" />
        </button>
        {expanded && <div className="repository-directory" id="repository-directory" role="group" aria-label="来源仓库">
          {repositories.map(repo => <button type="button" key={repo.key} className="repository-option"
            title={repo.location ? repo.name + ' · ' + repo.location : repo.name} aria-pressed={repo.key === active}
            onClick={() => onRepository(repo.key)}>
            <i className="folder-icon" aria-hidden="true" />
            <span className="repository-name">{repo.name}
              {repo.location && repo.location !== 'github.com' && <small>{repo.location}</small>}
            </span>
            <span className="repository-count" aria-label={repo.count + ' 个 skill'}>{repo.count}</span>
          </button>)}
          {!repositories.length && <p className="directory-empty">{loading ? '正在读取仓库…' : '当前范围没有匹配项'}</p>}
        </div>}
      </>}
    </section>
  </aside>;
}
