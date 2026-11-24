import { useCallback, useEffect, useRef, useState } from 'react';
import type { Facets, IndexResponse } from '../api/types';
import { PAGE_SIZE, api } from '../api/endpoints';
import { ActiveFilters, type ActiveFilterChip } from '../components/ActiveFilters';
import { DetailEmpty } from '../components/DetailEmpty';
import { FileOverlay } from '../components/FileOverlay';
import { FilterRail } from '../components/FilterRail';
import { SkillDetail } from '../components/SkillDetail';
import { SkillList } from '../components/SkillList';
import { isTypingTarget } from '../lib/dom';
import { EMPTY_FILTERS, hasActiveFilters, toggleFacet, type FacetAxis, type Filters } from '../lib/filters';
import { sourceTail } from '../lib/format';
import { confidenceLabel, healthLabel, hostKindLabel } from '../lib/labels';
import { registerSearchFocus } from '../lib/searchFocus';
import { useDebounced } from '../lib/useDebounced';
import { useApi } from '../lib/useApi';

export interface LibraryPageProps {
  selectedKey: string | null;
  onOpenSkill: (identityKey: string) => void;
}

function filterKeyOf(filters: Filters): string {
  return [filters.q, filters.host, filters.source, filters.confidence, filters.health].join('\u0000');
}

export function LibraryPage({ selectedKey, onOpenSkill }: LibraryPageProps) {
  const facets = useApi<Facets>((signal) => api.facets(signal), []);
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [openFile, setOpenFile] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const detailPaneRef = useRef<HTMLDivElement>(null);
  const listColumnRef = useRef<HTMLDivElement>(null);
  const debouncedSearch = useDebounced(search, 200);

  const filterKey = filterKeyOf(filters);

  // The debounced query is what the request uses; clearing filters bypasses the delay.
  useEffect(() => {
    setFilters((current) => (current.q === debouncedSearch ? current : { ...current, q: debouncedSearch }));
  }, [debouncedSearch]);

  useEffect(() => {
    setPage(0);
  }, [filterKey]);

  const list = useApi<IndexResponse>(
    (signal) =>
      api.index(
        {
          q: filters.q,
          host: filters.host,
          source: filters.source,
          confidence: filters.confidence,
          health: filters.health,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        },
        signal,
      ),
    [filterKey, page],
  );

  const facetsData = facets.state.status === 'ready' ? facets.state.data : null;
  const confidenceLabels = facetsData === null ? {} : facetsData.confidenceLabels;
  const healthLabels = facetsData === null ? {} : facetsData.healthLabels;
  const hasFilters = hasActiveFilters(filters);

  const toggleFacetValue = useCallback((axis: FacetAxis, value: string) => {
    setFilters((current) => toggleFacet(current, axis, value));
  }, []);

  const clearFilters = useCallback(() => {
    setSearch('');
    setFilters(EMPTY_FILTERS);
    setPage(0);
  }, []);

  useEffect(() => {
    detailPaneRef.current?.scrollTo({ top: 0 });
  }, [selectedKey]);

  useEffect(() => {
    setOpenFile(null);
  }, [selectedKey]);

  useEffect(() => {
    return registerSearchFocus(() => {
      const input = searchInputRef.current;
      if (input !== null) {
        input.focus();
        input.select();
      }
    });
  }, []);

  const moveRowFocus = useCallback((direction: 1 | -1) => {
    const container = listColumnRef.current;
    if (container === null) {
      return;
    }
    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('[data-row-index]'));
    if (buttons.length === 0) {
      return;
    }
    const focused = document.activeElement instanceof HTMLElement ? document.activeElement.closest('[data-row-index]') : null;
    const current = focused instanceof HTMLButtonElement ? buttons.indexOf(focused) : -1;
    const next =
      current === -1
        ? direction === 1
          ? 0
          : buttons.length - 1
        : Math.min(Math.max(current + direction, 0), buttons.length - 1);
    buttons[next]?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === 'Escape') {
        if (openFile !== null) {
          event.preventDefault();
          setOpenFile(null);
          return;
        }
        if (hasFilters) {
          event.preventDefault();
          clearFilters();
        }
        return;
      }

      if (isTypingTarget(event.target)) {
        return;
      }

      if (event.key === '/') {
        event.preventDefault();
        const input = searchInputRef.current;
        if (input !== null) {
          input.focus();
          input.select();
        }
        return;
      }

      if (openFile !== null) {
        return;
      }

      if (event.key === 'ArrowDown' || event.key === 'j') {
        event.preventDefault();
        moveRowFocus(1);
      } else if (event.key === 'ArrowUp' || event.key === 'k') {
        event.preventDefault();
        moveRowFocus(-1);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [openFile, hasFilters, clearFilters, moveRowFocus]);

  const chips: ActiveFilterChip[] = [];
  if (filters.q !== '') {
    chips.push({
      key: 'q',
      label: `搜索「${filters.q}」`,
      onRemove: () => {
        setSearch('');
        setFilters((current) => ({ ...current, q: '' }));
      },
    });
  }
  if (filters.host !== '') {
    chips.push({
      key: 'host',
      label: `宿主根：${hostKindLabel(filters.host)}`,
      onRemove: () => {
        toggleFacetValue('host', filters.host);
      },
    });
  }
  if (filters.source !== '') {
    chips.push({
      key: 'source',
      label: `来源：${sourceTail(filters.source)}`,
      onRemove: () => {
        toggleFacetValue('source', filters.source);
      },
    });
  }
  if (filters.confidence !== '') {
    chips.push({
      key: 'confidence',
      label: `可信度：${confidenceLabel(filters.confidence, confidenceLabels)}`,
      onRemove: () => {
        toggleFacetValue('confidence', filters.confidence);
      },
    });
  }
  if (filters.health !== '') {
    chips.push({
      key: 'health',
      label: `健康：${healthLabel(filters.health, healthLabels)}`,
      onRemove: () => {
        toggleFacetValue('health', filters.health);
      },
    });
  }

  return (
    <div className={selectedKey === null ? 'library' : 'library library--detail'}>
      <FilterRail
        search={search}
        onSearchChange={setSearch}
        searchInputRef={searchInputRef}
        facets={facets.state}
        filters={filters}
        onToggleFacet={toggleFacetValue}
        onClearFilters={clearFilters}
        hasFilters={hasFilters}
        onRetryFacets={facets.reload}
      />

      <div className="list-column" ref={listColumnRef}>
        <ActiveFilters chips={chips} onClearAll={clearFilters} />
        <SkillList
          state={list.state}
          page={page}
          pageSize={PAGE_SIZE}
          selectedKey={selectedKey}
          hasFilters={hasFilters}
          confidenceLabels={confidenceLabels}
          healthLabels={healthLabels}
          onOpenSkill={onOpenSkill}
          onPageChange={setPage}
          onClearFilters={clearFilters}
          onRefresh={list.reload}
        />
      </div>

      <div className="detail-pane" ref={detailPaneRef}>
        {selectedKey === null ? (
          <DetailEmpty />
        ) : (
          <SkillDetail identityKey={selectedKey} healthLabels={healthLabels} onOpenFile={setOpenFile} />
        )}
      </div>

      {openFile === null || selectedKey === null ? null : (
        <FileOverlay
          skillKey={selectedKey}
          rel={openFile}
          onClose={() => {
            setOpenFile(null);
          }}
        />
      )}
    </div>
  );
}
