import type { ReactNode } from 'react';

export interface PageHeaderProps {
  title: string;
  sub?: ReactNode;
  aside?: ReactNode;
}

export function PageHeader({ title, sub, aside }: PageHeaderProps) {
  return (
    <header className="page-head">
      <div className="page-head-main">
        <h1 className="page-title">{title}</h1>
        {sub === undefined ? null : <p className="page-sub">{sub}</p>}
      </div>
      {aside === undefined ? null : <div className="page-head-aside">{aside}</div>}
    </header>
  );
}
