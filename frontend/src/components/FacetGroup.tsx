import type { ReactNode } from 'react';

export interface FacetGroupProps {
  title: string;
  hint?: string;
  scroll?: boolean;
  children: ReactNode;
}

export function FacetGroup({ title, hint, scroll = false, children }: FacetGroupProps) {
  return (
    <section className="facet-group">
      <header className="facet-group-head">
        <h3>{title}</h3>
        {hint === undefined ? null : <span className="facet-group-hint">{hint}</span>}
      </header>
      <div className={`facet-list${scroll ? ' facet-list--scroll' : ''}`}>{children}</div>
    </section>
  );
}
