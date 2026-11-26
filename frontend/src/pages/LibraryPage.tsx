import { useEffect, useRef, useState } from 'react';
import { api, PAGE_SIZE, VERSION_BATCH_LIMIT } from '../api/endpoints';
import { ApiError, describeError } from '../api/client';
import type { AssetChanges, SkillSummary } from '../api/types';
import { FileOverlay } from '../components/FileOverlay';
import { CategoryDirectory } from '../components/CategoryDirectory';
import { ActionNotice, type Notice } from '../components/ActionNotice';
import { FacetGroups } from '../components/FilterRail';
import { SkillList } from '../components/SkillList';
import { LibraryNavigation, libraryViews } from '../components/LibraryNavigation';
import { SkillDetail } from '../components/SkillDetail';
import type { DocumentTarget } from '../components/SkillBody';
import { isTypingTarget } from '../lib/dom';
import { hasActiveFilters, type FacetAxis, type Filters } from '../lib/filters';
import { hostKindLabel } from '../lib/labels';
import { libraryHref, libraryParams, navigate, sourcePages, updateLibraryParams, type LibraryPosition } from '../lib/route';
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
  const category = params.get('category') || '';
  const layout = params.get('layout');
  const grouped = layout ? layout === 'repository' : view === 'github' || view === 'mine';
  const repository = params.get('repo') || '';
  const groupPages = sourcePages(params);
  const groupQuery = grouped && Object.keys(groupPages).length ? JSON.stringify(groupPages) : '';
  const filters: Filters = { q: params.get('q') || '', host: params.get('host') || '', source: params.get('source') || '',
    confidence: params.get('confidence') || '', health: params.get('health') || '' };
  const page = Math.max(0, Number.parseInt(params.get('page') || '1', 10) - 1 || 0);
  const search = useDebounced(filters.q, 180);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [checkingPage, setCheckingPage] = useState(false);
  const pending = useRef(false);
  const [notice, setNotice] = useState<Notice>();
  const setMessage = (text: string) => setNotice(text ? { text } : undefined);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 860px)').matches);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 860px)');
    const changed = () => setNarrow(media.matches);
    media.addEventListener('change', changed);
    changed();
    return () => media.removeEventListener('change', changed);
  }, []);
  const restore = useRef<{ key: string; scroll: number } | null>(null);
  const [files, setFiles] = useState<DocumentTarget[]>([]);
  const searchInput = useRef<HTMLInputElement>(null);
  const listColumn = useRef<HTMLDivElement>(null);
  const detailPane = useRef<HTMLDivElement>(null);
  const advanced = useRef<HTMLDetailsElement>(null);
  const lastPreview = useRef<string | null>(null);
  const query = params.toString();
  const facets = useApi(signal => api.facets(signal), [generation, epoch], true);
  const [layoutFocus, setLayoutFocus] = useState('');
  const focus = selectedKey || layoutFocus;
  const list = useApi(signal => api.index({
    ...filters, q: search, agent, category, view, layout: grouped ? 'sources' : 'flat',
    groupPages: groupQuery, repository: grouped ? repository : '',
    focus, limit: PAGE_SIZE, offset: page * PAGE_SIZE,
  }, signal), [search, agent, category, view, grouped, groupQuery, repository, focus, filters.host, filters.source,
    filters.confidence, filters.health, page, generation, epoch], true);
  const data = list.state.status === 'ready' ? list.state.data : null;
  const groups = data?.repositories ?? [];
  const onlyGroup = grouped && groups.length === 1 ? groups[0] : undefined;
  const displayedPage = onlyGroup ? (onlyGroup.page || 1) - 1 : data ? Math.floor(data.offset / PAGE_SIZE) : page;
  const items = list.state.status === 'ready' ? list.state.data.items : [];
  const linkedItem = grouped && repository ? items.find(item => item.repository.key === repository) : undefined;
  const first = list.state.status === 'loading' ? lastPreview.current : (linkedItem ?? items[0])?.identity_key ?? null;
  const preview = selectedKey ?? items.find(item => item.identity_key === layoutFocus)?.identity_key ?? first;
  function positionFor(key: string | null): LibraryPosition | undefined {
    if (!grouped) return { repo: '', page: displayedPage };
    const item = items.find(i => i.identity_key === key);
    const group = item && groups.find(g => g.key === item.repository.key);
    return group?.page ? { repo: group.key, page: group.page - 1 } : undefined;
  }
  const position = positionFor(preview);
  const hasAdvanced = Boolean(filters.host || filters.source || filters.confidence || filters.health);
  const hasFilters = hasActiveFilters(filters) || Boolean(agent || category);
  const file = files[files.length - 1];
  const refreshData = () => setEpoch(n => n + 1);

  useEffect(() => { sessionStorage.setItem('skilldesk.library-query', query); }, [query]);
  useEffect(() => { if (list.state.status === 'ready') lastPreview.current = list.state.data.items[0]?.identity_key ?? null; }, [list.state]);
  useEffect(() => {
    if (!restore.current && !grouped && list.state.status === 'ready' && page && list.state.data.total <= page * PAGE_SIZE) {
      const last = Math.max(1, Math.ceil(list.state.data.total / PAGE_SIZE));
      updateLibraryParams({ page: last > 1 ? String(last) : '' });
    }
  }, [list.state, page, grouped]);
  useEffect(() => {
    const saved = restore.current;
    if (saved && list.state.data?.items.some(i => i.identity_key === saved.key)) {
      listColumn.current?.querySelector('.rows-scroll')?.scrollTo({ top: saved.scroll });
      restore.current = null;
    }
  }, [list.state]);
  useEffect(() => { setFiles([]); detailPane.current?.scrollTo({ top: 0 }); }, [preview]);
  useEffect(() => registerSearchFocus(() => { searchInput.current?.focus(); searchInput.current?.select(); }), []);

  function change(key: string, value: string) {
    setMessage('');
    setLayoutFocus('');
    updateLibraryParams({ [key]: value, page: '', repo: '', groups: '' });
  }
  function changeLayout(next: boolean) {
    if (next === grouped) return;
    setMessage('');
    setLayoutFocus(preview || '');
    const pages = sourcePages(libraryParams());
    const reading = next && selectedKey && items.find(item => item.identity_key === selectedKey);
    if (reading) delete pages[reading.repository.key];
    updateLibraryParams({ layout: next ? 'repository' : 'flat', repo: '', page: '',
      groups: Object.keys(pages).length ? JSON.stringify(pages) : '' }, true);
  }
  function changeGroup(key: string, nextPage: number) {
    updateLibraryParams({ groups: JSON.stringify({ ...sourcePages(libraryParams()), [key]: nextPage }) }, true);
  }
  function changePage(nextPage: number) {
    setLayoutFocus('');
    if (onlyGroup) changeGroup(onlyGroup.key, nextPage + 1);
    else updateLibraryParams({ page: nextPage ? String(nextPage + 1) : '', repo: '' });
  }
  function openSkill(key: string) {
    onOpenSkill(key, positionFor(key));
  }
  function toggle(axis: FacetAxis, value: string) { change(axis, filters[axis] === value ? '' : value); }
  function clear() {
    setMessage(''); setLayoutFocus('');
    updateLibraryParams({ q: '', host: '', source: '', confidence: '', health: '', agent: '', category: '', page: '', repo: '', groups: '' });
  }
  async function save(item: SkillSummary, changes: AssetChanges, reread = false): Promise<boolean> {
    if (pending.current) return false;
    pending.current = true; setBusy(true); setMessage('');
    try {
      const current = reread ? await api.skill(item.identity_key) : item;
      let updated: SkillSummary;
      try { updated = await api.patch(current, changes); }
      catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) throw err;
        const fresh = await api.skill(item.identity_key);
        if (changes.favorite !== undefined) {
          updated = fresh.favorite === changes.favorite ? fresh : await api.patch(fresh, changes);
        } else if ('category' in changes) {
          const oldOverride = current.category.manual ? current.category.key : null;
          const newOverride = fresh.category.manual ? fresh.category.key : null;
          if (newOverride !== oldOverride && newOverride !== changes.category) throw err;
          updated = newOverride === changes.category ? fresh : await api.patch(fresh, changes);
        } else {
          // The revision covers the whole library. An unrelated edit can safely be retried.
          const sameTracking = current.hasTrackingOverride === fresh.hasTrackingOverride
            && current.upstream?.repo === fresh.upstream?.repo && current.upstream?.path === fresh.upstream?.path;
          if (!sameTracking || (changes.mine && current.provenance.confidence !== fresh.provenance.confidence)) throw err;
          updated = await api.patch(fresh, changes);
        }
      }
      if (changes.favorite === false) {
        const location = window.location.hash;
        const scroll = listColumn.current?.querySelector('.rows-scroll')?.scrollTop ?? 0;
        setNotice({ text: '已取消收藏 ' + item.name, action: { label: '撤销', run: async () => {
          if (await save(updated, { favorite: true }, true) && view === 'favorites') {
            restore.current = { key: item.identity_key, scroll };
            navigate(location);
          }
        } } });
      } else if ('category' in changes) {
        setNotice({ text: item.name + ' · ' + updated.category.name, action: { label: '撤销', run: () =>
          void save(updated, { category: current.category.manual ? current.category.key : null }) } });
      } else setMessage((changes.favorite ? '已收藏 ' : '已保存来源 · ') + item.name);
      if ('mine' in changes || 'github' in changes) onScanned();
      if (selectedKey === item.identity_key && ((view === 'mine' && !updated.mine) || (view === 'github' && updated.mine))) navigate(libraryHref());
      refreshData();
      return true;
    } catch (error) {
      setNotice({ text: item.name + ' · ' + describeError(error), error: true,
        action: { label: '重试保存', run: () => void save(item, changes, true) } });
      refreshData(); return false;
    }
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
    setMessage('正在检查 ' + candidates.length + ' 项的上游版本…');
    const checked: { error?: string }[] = [];
    try {
      for (let start = 0; start < candidates.length; start += VERSION_BATCH_LIMIT) {
        const batch = candidates.slice(start, start + VERSION_BATCH_LIMIT);
        const result = await api.checkBatch(batch.map(i => i.identity_key));
        checked.push(...result.items);
        if (result.items.length < batch.length || result.items.some(item => item.status === 429)) break;
      }
      const errors = checked.filter(i => i.error);
      const skipped = candidates.length - checked.length;
      setMessage('已检查 ' + (checked.length - errors.length) + ' 项' +
        (errors.length ? ' · ' + errors.length + ' 项失败 · ' + errors[0]?.error : '') + (skipped ? ' · ' + skipped + ' 项待检查' : ''));
    } catch (err) {
      setNotice({ text: (checked.length ? '已处理 ' + checked.length + ' 项 · ' : '') + describeError(err), error: true });
    } finally {
      if (checked.length) refreshData();
      setCheckingPage(false);
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]') || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      const inSearch = event.target === searchInput.current;
      if (event.key === 'Escape') {
        if (files.length) setFiles(current => current.slice(0, -1));
        else if (inSearch && filters.q) change('q', '');
        else if (isTypingTarget(event.target)) return;
        else if (advanced.current?.open && advanced.current.contains(event.target as Node)) {
          advanced.current.open = false; advanced.current.querySelector('summary')?.focus();
        } else if (selectedKey && narrow) navigate(libraryHref(position));
        else return;
        event.preventDefault(); return;
      }
      if (files.length || (narrow && selectedKey)) return;
      if (isTypingTarget(event.target) && !inSearch) return;
      if (event.key === '/' && !inSearch) { event.preventDefault(); searchInput.current?.focus(); return; }
      const navigable = 'button[data-row-index], button.source-heading';
      if (!inSearch && !(event.target instanceof Element && event.target.closest(navigable))) return;
      const rows = Array.from(listColumn.current?.querySelectorAll<HTMLButtonElement>(navigable) ?? []);
      if (inSearch && event.key === 'Enter' && search === filters.q && items[0]) {
        event.preventDefault(); openSkill(items[0].identity_key); searchInput.current?.blur(); return;
      }
      if (inSearch && event.key === 'Enter' && !items.length && rows[0]) {
        event.preventDefault(); rows[0].focus(); return;
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
    <LibraryNavigation view={view} onView={id => change('view', id === 'all' ? '' : id)}>
      <CategoryDirectory selected={category} groups={data?.categories ?? []} pending={data?.pendingCategories ?? 0}
        onSelect={key => change('category', key)} onRefresh={refreshData} />
    </LibraryNavigation>
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
            {checkingPage ? '正在检查…' : grouped && groups.length > 1 ? '检查已展开项的版本' : '检查本页版本'}</button>}
        <details ref={advanced} className="advanced"><summary>{hasAdvanced ? '已筛选' : '更多筛选'}</summary>
          <div className="facet-popover">{facetData ? <FacetGroups facets={facetData} filters={filters} onToggleFacet={toggle} />
            : <button type="button" className="button" onClick={facets.reload}>重新加载筛选</button>}
            {hasFilters && <button type="button" className="button" onClick={clear}>清空筛选</button>}
          </div></details>
      </div>
    </header>
    {notice && <ActionNotice key={notice.text} note={notice} busy={busy} close={() => setNotice(undefined)} />}
    <div className="library-panes">
      <div className="list-column" ref={listColumn}>
        <SkillList view={view} state={list.state} page={displayedPage} pageSize={PAGE_SIZE} selectedKey={preview} busy={busy}
          title={data?.categories.find(group => group.key === category)?.name || libraryViews.find(option => option.id === view)?.label || '全部'}
          grouped={grouped} showCategory={!category}
          groupPages={groupPages} onGroupPage={changeGroup} onLayout={changeLayout}
          revealKey={selectedKey || layoutFocus || linkedItem?.identity_key || ''}
          scrollKey={JSON.stringify([view, agent, category, filters, grouped, grouped ? 0 : displayedPage])}
          hasFilters={hasFilters} healthLabels={facetData?.healthLabels ?? {}}
          onFavorite={item => void save(item, { favorite: !item.favorite })} onOpenSkill={openSkill}
          onPageChange={changePage}
          onClearFilters={clear} onRefresh={() => void rescan()} />
      </div>
      <div className="detail-pane" ref={detailPane}>
        {!narrow && !preview && grouped && Boolean(data?.total) && <p className="detail-empty">展开来源，选择要阅读的技能。</p>}
        {preview && (!narrow || selectedKey) && <SkillDetail key={preview} identityKey={preview}
        generation={generation + '-' + epoch} backHref={libraryHref(position)} busy={busy}
        onSave={save} onFile={openFile} onVersion={refreshData} onMaintenance={result => {
          const label = result.action === 'update' ? '已升级' : result.action === 'unlink' ? '已解除链接' : '已卸载';
          setNotice({ text: (result.outcome === 'record' ? '已更新安装记录' : label) + ' · ' + result.target, backup: result.backup });
          if (result.action !== 'update') navigate(libraryHref(position));
          refreshData(); onScanned();
        }} />}</div>
    </div>
    {file && preview && <FileOverlay key={file.rel} skillKey={preview} rel={file.rel} anchor={file.anchor} raw={file.raw} onFile={openFile}
      onClose={() => setFiles(current => current.slice(0, -1))} />}
  </div>;
}
