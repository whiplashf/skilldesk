import type { ReactNode } from 'react';

export const libraryViews = [
  { id: 'all', label: '全部' },
  { id: 'github', label: 'GitHub 引入' },
  { id: 'mine', label: '我写的' },
  { id: 'favorites', label: '已收藏' },
] as const;

interface Props {
  children: ReactNode;
  view: string;
  onView: (view: string) => void;
}

export function LibraryNavigation({ children, view, onView }: Props) {
  return <aside className="library-navigation" aria-label="技能库目录">
    <h2 className="nav-title">技能库</h2>
    <div className="scope-links" role="group" aria-label="查看范围">
      {libraryViews.map(({ id, label }) => <button key={id} type="button" aria-pressed={view === id} onClick={() => onView(id)}>
        <i aria-hidden="true" className={'scope-icon icon-' + id} />{label}
      </button>)}
    </div>
    {children}
  </aside>;
}
