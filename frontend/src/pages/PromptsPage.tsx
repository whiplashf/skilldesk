import { useEffect, useRef, useState } from 'react';
import { api } from '../api/endpoints';
import { describeError } from '../api/client';
import type { SavedPrompt } from '../api/types';
import { ActionNotice, type Notice } from '../components/ActionNotice';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { PageHeader } from '../components/PageHeader';
import { hasNewPromptDraft, PromptEditor } from '../components/PromptEditor';
import { PromptRow } from '../components/PromptRow';
import { registerSearchFocus } from '../lib/searchFocus';
import { useApi } from '../lib/useApi';

export function PromptsPage() {
  const { state, reload } = useApi(api.prompts, [], true);
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>();
  const [editor, setEditor] = useState<SavedPrompt | 'new'>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>();
  useEffect(() => registerSearchFocus(() => { search.current?.focus(); search.current?.select(); }), []);
  useEffect(() => {
    window.addEventListener('focus', reload);
    return () => window.removeEventListener('focus', reload);
  }, [reload]);

  const items = state.data?.items ?? [];
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  const categories = [...counts.keys()].sort((a, b) => a && b ? a.localeCompare(b, 'zh-CN') : Number(!a) - Number(!b));
  const activeCategory = category !== null && counts.has(category) ? category : null;
  const term = query.trim().toLowerCase();
  const matches = (item: SavedPrompt) => !term || [item.title, item.category, item.body].some(s => s.toLowerCase().includes(term));
  const results = items.filter(item => (activeCategory === null || item.category === activeCategory) && matches(item));
  const openId = expanded === undefined && results.length === 1 ? results[0]?.id : expanded;
  function selectCategory(value: string | null) {
    setCategory(value); setExpanded(undefined);
  }
  function show(item: SavedPrompt) {
    if (activeCategory !== null) setCategory(item.category);
    if (!matches(item)) setQuery('');
    setExpanded(item.id);
  }
  function saved(item: SavedPrompt) {
    setEditor(undefined); show(item); reload();
    setNotice({ text: '已将「' + item.title + '」保存到仓库' });
  }
  async function restore(item: SavedPrompt, revision: number) {
    setBusy(true);
    try {
      const { body, title, category } = item;
      show(await api.savePrompt(item.id, { body, title, category }, revision));
      setNotice({ text: '已恢复「' + item.title + '」' });
    } catch (err) {
      setNotice({ text: describeError(err), error: true, action: { label: '重试恢复', run: () => void restore(item, revision) } });
    } finally { setBusy(false); reload(); }
  }
  async function remove(item: SavedPrompt) {
    setBusy(true);
    try {
      const { revision } = await api.deletePrompt(item);
      setNotice({ text: '已删除「' + item.title + '」', action: { label: '撤销', run: () => void restore(item, revision) } });
    } catch (err) { setNotice({ text: describeError(err), error: true }); }
    finally { setBusy(false); reload(); }
  }
  return <div className={'prompt-workspace' + (items.length ? '' : ' without-categories')}>
    {items.length > 0 && <aside className="prompt-sidebar" aria-label="提示词分类">
      <h2>分类</h2><div className="scope-links">
        <button type="button" aria-pressed={activeCategory === null} onClick={() => selectCategory(null)}>
          <span>全部</span><small>{items.length}</small></button>
        {categories.map(name => <button type="button" key={name} aria-pressed={activeCategory === name} onClick={() => selectCategory(name)}>
          <span>{name || '未分类'}</span><small>{counts.get(name)}</small></button>)}
      </div>
    </aside>}
    <section className="prompt-content" aria-label="提示词列表"><div className="prompt-sheet">
      <PageHeader title={activeCategory === null ? '提示词库' : activeCategory || '未分类'}
        sub={state.data?.catalogUrl && <a href={state.data.catalogUrl} target="_blank" rel="noreferrer">GitHub 提示词目录 ↗</a>}
        aside={<button type="button" className="button prompt-primary" onClick={() => setEditor('new')}>
          {hasNewPromptDraft() ? '继续草稿' : '新建提示词'}</button>} />
      {(items.length > 0 || query) && <div className="prompt-search">
        <label className="search-field"><i className="search-icon" aria-hidden="true" />
          <input ref={search} type="search" aria-label="搜索提示词" placeholder="搜索标题、分类或正文" value={query}
            onChange={e => { setQuery(e.target.value); setExpanded(undefined); }}
            onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); setQuery(''); } }} /><kbd aria-hidden="true">/</kbd></label>
        <span className="pane-count" aria-live="polite">{results.length} 条</span>
      </div>}
      {notice && <ActionNotice note={notice} busy={busy} close={() => setNotice(undefined)} />}
      {state.status === 'loading' ? <p role="status">正在读取提示词…</p>
        : state.status === 'error' ? <ErrorState message={state.error} onRetry={reload} />
        : results.length ? <ul className="prompt-list">{results.map(item =>
          <PromptRow key={item.id} item={item} expanded={openId === item.id} showCategory={activeCategory === null}
            busy={busy} onToggle={() => setExpanded(openId === item.id ? null : item.id)}
            onEdit={() => setEditor(item)} onDelete={() => void remove(item)} />)}</ul>
        : items.length ? <EmptyState title="没有匹配的提示词" actionLabel="清除搜索" onAction={() => setQuery('')} />
        : <EmptyState title="还没有提示词" hint="点「新建提示词」，粘贴一段想留着下次用的正文。" />}
    </div></section>
    {editor && <PromptEditor item={editor === 'new' ? null : editor} category={activeCategory ?? ''}
      categories={categories.filter(Boolean)} onClose={() => setEditor(undefined)} onSaved={saved} />}
  </div>;
}
