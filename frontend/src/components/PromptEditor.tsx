import { useEffect, useRef, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { PromptText, SavedPrompt } from '../api/types';

type Draft = PromptText & { id: string; revision: number };
const prefix = 'skilldesk.prompt-draft.';
const sessionDrafts = new Map<string, Draft>();

function readDraft(key: string): Draft | undefined {
  if (sessionDrafts.has(key)) return sessionDrafts.get(key);
  try {
    const value = JSON.parse(sessionStorage.getItem(prefix + key) ?? 'null');
    if (value && /^[0-9a-f]{32}$/.test(value.id) && Number.isSafeInteger(value.revision) && value.revision >= 0
      && ['body', 'title', 'category'].every(field => typeof value[field] === 'string')) return value;
  } catch { /* Storage may be unavailable in private browsing. */ }
}

function keepDraft(key: string, value?: Draft) {
  if (value) sessionDrafts.set(key, value);
  else sessionDrafts.delete(key);
  try {
    if (value) sessionStorage.setItem(prefix + key, JSON.stringify(value));
    else sessionStorage.removeItem(prefix + key);
  } catch { /* The in-memory draft stays available in this tab. */ }
}

function makeId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

export function hasNewPromptDraft() { return Boolean(readDraft('new')); }

interface Props {
  item: SavedPrompt | null;
  category: string;
  categories: string[];
  onClose: () => void;
  onSaved: (item: SavedPrompt) => void;
}

export function PromptEditor({ item, category, categories, onClose, onSaved }: Props) {
  const key = item?.id ?? 'new';
  const [base] = useState<Draft>(() => item ?? { id: makeId(), revision: 0, body: '', title: '', category });
  const [draft, setDraft] = useState(() => readDraft(key) ?? base);
  const dirty = draft.body !== base.body || draft.title !== base.title || draft.category !== base.category;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal(); body.current?.focus();
    return () => node?.close();
  }, []);
  function change(field: keyof PromptText, value: string) {
    const next = { ...draft, [field]: value };
    setDraft(next);
    keepDraft(key, next);
  }
  function close(discard = false) {
    if (discard || !dirty) keepDraft(key);
    onClose();
  }
  async function save(asCopy = false) {
    if (busy || !draft.body.trim()) return;
    setBusy(true); setError('');
    try {
      const pending = asCopy ? { ...draft, id: makeId(), revision: 0 } : draft;
      if (asCopy) { setDraft(pending); keepDraft(key, pending); setConflict(false); }
      const { id, revision, title, category, body } = pending;
      const saved = await api.savePrompt(id, { title, category, body }, revision);
      keepDraft(key);
      onSaved(saved);
    } catch (err) {
      setError(describeError(err));
      if (err instanceof ApiError && err.status === 409) setConflict(true);
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="prompt-dialog" aria-labelledby="prompt-editor-title"
    onCancel={e => { e.preventDefault(); if (!busy) close(); }}>
    <form className="prompt-form" onSubmit={e => { e.preventDefault(); void save(conflict); }}>
      <h2 id="prompt-editor-title">{item ? '编辑提示词' : '新建提示词'}</h2>
      <label>提示词正文<textarea ref={body} required disabled={busy} rows={9} maxLength={200000} value={draft.body}
        placeholder="粘贴或写下要反复使用的提示词…" onChange={e => change('body', e.target.value)} /></label>
      <div className="prompt-fields">
        <label>标题<input disabled={busy} maxLength={120} placeholder="留空时使用正文首行" value={draft.title} onChange={e => change('title', e.target.value)} /></label>
        <label>分类<input disabled={busy} maxLength={80} list={categories.length ? 'prompt-categories' : undefined} placeholder="选择或输入分类" value={draft.category}
          onChange={e => change('category', e.target.value)} /></label>
        {categories.length > 0 && <datalist id="prompt-categories">{categories.map(name => <option key={name} value={name} />)}</datalist>}
      </div>
      {error && <p className="action-message" role="alert">{error}{conflict && '。可以将当前草稿另存为副本。'}</p>}
      <div className="prompt-form-actions">
        {dirty && <button type="button" className="link-button discard-draft" disabled={busy} onClick={() => close(true)}>放弃修改</button>}
        <button type="button" className="button" disabled={busy} onClick={() => close()}>{dirty ? '稍后继续' : '取消'}</button>
        <button className="button prompt-primary" disabled={busy || !draft.body.trim() || (Boolean(item) && !dirty && !conflict)}>
          {busy ? '正在保存…' : conflict ? '另存为副本' : item && item.id !== draft.id ? '保存副本' : '保存提示词'}</button>
      </div>
    </form>
  </dialog>;
}
