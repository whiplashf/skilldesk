import { useEffect, useRef, useState } from 'react';
import { api, PAGE_SIZE } from '../api/endpoints';
import { ApiError, describeError } from '../api/client';
import type { AssetChanges, SkillSummary } from '../api/types';
import { FileOverlay } from '../components/FileOverlay';
import { FacetGroups } from '../components/FilterRail';
import { SkillList } from '../components/SkillList';
import { LibraryNavigation, libraryViews } from '../components/LibraryNavigation';
import { SkillDetail } from '../components/SkillDetail';
import type { DocumentTarget } from '../components/SkillBody';
import { isTypingTarget } from '../lib/dom';
import { hasActiveFilters, type FacetAxis, type Filters } from '../lib/filters';
import { hostKindLabel } from '../lib/labels';
import { libraryHref, libraryParams, navigate, updateLibraryParams, type LibraryPosition } from '../lib/route';
import { registerSearchFocus } from '../lib/searchFocus';
import { useApi } from '../lib/useApi';
import { useDebounced } from '../lib/useDebounced';

interface Props {
  selectedKey: string | null;
  onOpenSkill: (key: string, position?: LibraryPosition) => void;
  generation: string;
  onScanned: () => void;
}

export function LibraryPage({ selectedKey, onOpenSkill, generation, onScanned }: Props) {
  const params = libraryParams();
  const view = params.get('view') || 'all';
  const agent = params.get('agent') || '';
  const layout = params.get('layout');
  const grouped = layout ? layout === 'repository' : view === 'github' || view === 'mine';
  const repository = params.get('repo') || '';
  const filters: Filters = { q: params.get('q') || '', host: params.get('host') || '', source: params.get('source') || '',
    confidence: params.get('confidence') || '', health: params.get('health') || '' };
  const page = Math.max(0, Number.parseInt(params.get('page') || '1', 10) - 1 || 0);
  const search = useDebounced(filters.q, 180);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [checkingPage, setCheckingPage] = useState(false);
  const pending = useRef(false);
  const [message, setMessage] = useState('');
  const [files, setFiles] = useState<DocumentTarget[]>([]);
  const searchInput = useRef<HTMLInputElement>(null);
  const listColumn = useRef<HTMLDivElement>(null);
  const detailPane = useRef<HTMLDivElement>(null);
  const advanced = useRef<HTMLDetailsElement>(null);
  const lastPreview = useRef<string | null>(null);
  const query = params.toString();
  const facets = useApi(signal => api.facets(signal), [generation, epoch], true);
  const focus = grouped ? selectedKey || '' : '';
  const list = useApi(signal => api.index({
    ...filters, q: search, agent, view, byRepository: grouped, repository: grouped ? repository : '',
    focus, limit: PAGE_SIZE, offset: page * PAGE_SIZE,
  }, signal), [search, agent, view, grouped, repository, focus, filters.host, filters.source,
    filters.confidence, filters.health, page, generation, epoch], true);
  const data = list.state.status === 'ready' ? list.state.data : null;
  const groups = data?.repositories ?? [];
  const activeGroup = groups.find(group => group.key === data?.activeRepository);
  const displayedPage = grouped && data ? Math.floor(data.offset / PAGE_SIZE) : page;
  const position = grouped && activeGroup ? { repo: activeGroup.key, page: displayedPage } : undefined;
  const items = list.state.status === 'ready' ? list.state.data.items : [];
  const first = list.state.status === 'loading' ? lastPreview.current : items[0]?.identity_key ?? null;
  const preview = selectedKey ?? first;
  const hasAdvanced = Boolean(filters.host || filters.source || filters.confidence || filters.health);
  const hasFilters = hasActiveFilters(filters) || Boolean(agent) || view !== 'all';
  const file = files[files.length - 1];
  const refreshData = () => setEpoch(n => n + 1);

  useEffect(() => { sessionStorage.setItem('skilldesk.library-query', query); }, [query]);
  useEffect(() => { if (list.state.status === 'ready') lastPreview.current = list.state.data.items[0]?.identity_key ?? null; }, [list.state]);
  useEffect(() => {
    if (!grouped && list.state.status === 'ready' && page && list.state.data.total <= page * PAGE_SIZE) {
      const last = Math.max(1, Math.ceil(list.state.data.total / PAGE_SIZE));
      updateLibraryParams({ page: last > 1 ? String(last) : '' });
    }
  }, [list.state, page, grouped]);
  useEffect(() => { setFiles([]); detailPane.current?.scrollTo({ top: 0 }); }, [preview]);
  useEffect(() => registerSearchFocus(() => { searchInput.current?.focus(); searchInput.current?.select(); }), []);

  function change(key: string, value: string) {
    setMessage('');
    updateLibraryParams({ [key]: value, page: '', ...(key === 'view' ? { repo: '', layout: '' } : {}) });
  }
  function changeLayout(next: boolean) {
    if (next === grouped) return;
    setMessage('');
    updateLibraryParams({ layout: next ? 'repository' : 'flat', repo: '', page: '' });
  }
  function openSkill(key: string) {
    onOpenSkill(key, position);
  }
  function toggle(axis: FacetAxis, value: string) { change(axis, filters[axis] === value ? '' : value); }
  function clear() { setMessage(''); updateLibraryParams({}, true); }
  async function save(item: SkillSummary, changes: AssetChanges): Promise<boolean> {
    if (pending.current) return false;
    pending.current = true; setBusy(true); setMessage('');
    try {
      const updated = await api.patch(item, changes);
      if ('mine' in changes || 'github' in changes) onScanned();
      if (selectedKey === item.identity_key && ((view === 'favorites' && !updated.favorite) ||
          (view === 'mine' && !updated.mine) || (view === 'github' && updated.mine))) navigate(libraryHref());
      refreshData();
      return true;
    } catch (error) { setMessage(describeError(error)); refreshData(); return false; }
    finally { pending.current = false; setBusy(false); }
  }
  async function rescan() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setMessage('');
    try {
      const health = await api.rescan();
      setMessage('已重新扫描 · ' + health.counts.skills + ' 个本机 skill');
      onScanned(); refreshData();
    } catch (error) { setMessage(describeError(error)); }
    finally { pending.current = false; setBusy(false); }
  }

  async function checkPage() {
    const candidates = items.filter(item => item.upstream?.path);
    if (!candidates.length || checkingPage) return;
    setCheckingPage(true);
    let completed = 0;
    let failed = 0;
    let errorMessage = '';
    try {
      for (const item of candidates) {
        setMessage('正在检查 ' + item.name + ' · ' + (completed + failed + 1) + '/' + candidates.length);
        try {
          await api.checkVersion(item.identity_key);
          completed++;
        } catch (error) {
          failed++;
          errorMessage = describeError(error);
          if (error instanceof ApiError && [0, 429, 502].includes(error.status)) break;
        }
      }
      setMessage('已检查 ' + completed + ' 项' + (failed ? ' · ' + failed + ' 项失败 · ' + errorMessage : ''));
      refreshData();
    } finally {
      setCheckingPage(false);
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]') || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'Escape') {
        if (files.length) setFiles(current => current.slice(0, -1));
        else if (advanced.current?.open) advanced.current.open = false;
        else if (selectedKey) navigate(libraryHref(position));
        else if (hasFilters) clear();
        else return;
        event.preventDefault(); return;
      }
      if (files.length) return;
      const inSearch = event.target === searchInput.current;
      if (isTypingTarget(event.target) && !inSearch) return;
      if (event.key === '/' && !inSearch) { event.preventDefault(); searchInput.current?.focus(); return; }
      const rows = Array.from(listColumn.current?.querySelectorAll<HTMLButtonElement>('button[data-row-index]') ?? []);
      if (inSearch && event.key === 'Enter' && search === filters.q && items[0]) {
        event.preventDefault(); openSkill(items[0].identity_key); searchInput.current?.blur(); return;
      }
      if (inSearch && !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      const down = event.key === 'ArrowDown' || event.key === 'j';
      if (rows.length && (down || event.key === 'ArrowUp' || event.key === 'k')) {
        const current = rows.indexOf(document.activeElement as HTMLButtonElement);
        rows[current < 0 ? (down ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, current + (down ? 1 : -1)))]?.focus();
        event.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  const facetData = facets.state.status === 'ready' ? facets.state.data : null;
  const openFile = (target: DocumentTarget) => setFiles(current => [...current, target]);
  return <div className={'library-workspace' + (selectedKey ? ' reading' : '')}>
    <LibraryNavigation view={view} grouped={grouped} active={activeGroup?.key || ''} repositories={groups}
      loading={list.state.status === 'loading'} onView={id => change('view', id === 'all' ? '' : id)}
      onLayout={changeLayout} onRepository={key => change('repo', key)} />
    <header className="library-tools">
      <div className="library-search-line">
        <div className="search-field">
          <i className="search-icon" aria-hidden="true" />
          <input aria-label="搜索本机 skill" type="search" ref={searchInput} placeholder="搜索名称或用途"
            value={filters.q} onChange={e => change('q', e.target.value)} /><kbd aria-hidden="true">/</kbd>
        </div>
        <label>可用 Agent <select aria-label="可用 Agent" value={agent} onChange={e => change('agent', e.target.value)}>
          <option value="">全部 Agent</option>
          {(facetData?.agents ?? []).map(a => <option key={a.value} value={a.value}>{hostKindLabel(a.value)}</option>)}
        </select></label>
        {view === 'github' && items.some(item => item.upstream?.path) &&
          <button type="button" className="button check-updates" disabled={checkingPage} onClick={() => void checkPage()}>
            {checkingPage ? '正在检查…' : '检查本页版本'}</button>}
        <details ref={advanced} className="advanced"><summary>{hasAdvanced ? '已筛选' : '更多筛选'}</summary>
          <div className="facet-popover">{facetData ? <FacetGroups facets={facetData} filters={filters} onToggleFacet={toggle} />
            : <button type="button" className="button" onClick={facets.reload}>重新加载筛选</button>}
            {hasFilters && <button type="button" className="button" onClick={clear}>清空筛选</button>}
          </div></details>
      </div>
      {message && <p className="action-message" role="status">{message}</p>}
    </header>
    <div className="library-panes">
      <div className="list-column" ref={listColumn}>
        <SkillList view={view} state={list.state} page={displayedPage} pageSize={PAGE_SIZE} selectedKey={preview} busy={busy}
          title={activeGroup?.name || libraryViews.find(option => option.id === view)?.label || '全部'}
          grouped={grouped}
          hasFilters={hasFilters} healthLabels={facetData?.healthLabels ?? {}}
          onFavorite={item => void save(item, { favorite: !item.favorite })} onOpenSkill={openSkill}
          onPageChange={n => updateLibraryParams({ page: n > 0 ? String(n + 1) : '', repo: activeGroup?.key || '' })}
          onClearFilters={clear} onRefresh={() => void rescan()} />
      </div>
      <div className="detail-pane" ref={detailPane}>{preview && <SkillDetail key={preview} identityKey={preview}
        generation={generation + '-' + epoch} backHref={libraryHref(position)} busy={busy}
        onSave={save} onFile={openFile} onVersion={refreshData} onMaintenance={result => {
          const label = result.action === 'update' ? '已升级' : result.action === 'unlink' ? '已解除链接' : '已卸载';
          setMessage(label + ' · ' + result.target + (result.backup ? '。原副本保存在 ' + result.backup : ''));
          if (result.action !== 'update') navigate(libraryHref(position));
          refreshData(); onScanned();
        }} />}</div>
    </div>
    {file && preview && <FileOverlay key={file.rel} skillKey={preview} rel={file.rel} anchor={file.anchor} raw={file.raw} onFile={openFile}
      onClose={() => setFiles(current => current.slice(0, -1))} />}
  </div>;
}
