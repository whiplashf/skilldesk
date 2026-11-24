export interface ActiveFilterChip {
  key: string;
  label: string;
  onRemove: () => void;
}

export interface ActiveFiltersProps {
  chips: ReadonlyArray<ActiveFilterChip>;
  onClearAll: () => void;
}

export function ActiveFilters({ chips, onClearAll }: ActiveFiltersProps) {
  if (chips.length === 0) {
    return null;
  }

  return (
    <div className="active-filters">
      <span className="active-filters-label">筛选</span>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          className="chip chip--active"
          title={`移除：${chip.label}`}
          onClick={chip.onRemove}
        >
          <span className="chip-text">{chip.label}</span>
          <span className="chip-x" aria-hidden="true">
            ×
          </span>
        </button>
      ))}
      <button type="button" className="link-button" onClick={onClearAll}>
        清空筛选
      </button>
    </div>
  );
}
