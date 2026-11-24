export interface Filters {
  q: string;
  host: string;
  source: string;
  confidence: string;
  health: string;
}

export type FacetAxis = 'host' | 'source' | 'confidence' | 'health';

export const EMPTY_FILTERS: Filters = {
  q: '',
  host: '',
  source: '',
  confidence: '',
  health: '',
};

export function hasActiveFilters(filters: Filters): boolean {
  return (
    filters.q !== '' ||
    filters.host !== '' ||
    filters.source !== '' ||
    filters.confidence !== '' ||
    filters.health !== ''
  );
}

/** The index API takes one value per axis, so facets behave as single-select toggles. */
export function toggleFacet(filters: Filters, axis: FacetAxis, value: string): Filters {
  const next = filters[axis] === value ? '' : value;
  return { ...filters, [axis]: next };
}
