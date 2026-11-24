export interface FacetRowProps {
  label: string;
  count?: number;
  active?: boolean;
  disabled?: boolean;
  mono?: boolean;
  sub?: string;
  title?: string;
  /** Renders an anchor row (navigational facet) instead of a toggle button. */
  href?: string;
  onSelect?: () => void;
}

export function FacetRow({
  label,
  count,
  active = false,
  disabled = false,
  mono = false,
  sub,
  title,
  href,
  onSelect,
}: FacetRowProps) {
  const className = `facet${active ? ' is-active' : ''}${disabled ? ' is-disabled' : ''}`;
  const content = (
    <>
      <span className="facet-label">
        <span className={`facet-name${mono ? ' mono' : ''}`}>{label}</span>
        {sub === undefined ? null : <span className="facet-sub">{sub}</span>}
      </span>
      {count === undefined ? null : <span className="facet-count">{count}</span>}
      {active ? (
        <span className="facet-x" aria-hidden="true">
          ×
        </span>
      ) : null}
    </>
  );

  if (href !== undefined) {
    return (
      <a className={`${className} facet--link`} href={href} title={title ?? label}>
        {content}
      </a>
    );
  }

  return (
    <button
      type="button"
      className={className}
      aria-pressed={active}
      disabled={disabled}
      title={title ?? label}
      onClick={onSelect}
    >
      {content}
    </button>
  );
}
