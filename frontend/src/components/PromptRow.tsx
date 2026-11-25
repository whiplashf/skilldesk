import { useEffect, useRef, useState } from 'react';
import type { SavedPrompt } from '../api/types';
import { copyText } from '../lib/clipboard';
import { PublishPrompt } from './PublishPrompt';

interface Props {
  item: SavedPrompt;
  expanded: boolean;
  showCategory: boolean;
  busy: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export function PromptRow({ item, expanded, showCategory, busy, onToggle, onEdit, onDelete }: Props) {
  const [copied, setCopied] = useState(false);
  const [manual, setManual] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const reset = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(reset.current), []);
  useEffect(() => { setManual(false); setCopied(false); setConfirming(false); }, [item.revision, expanded]);
  useEffect(() => {
    if (manual) { field.current?.focus(); field.current?.select(); }
  }, [manual]);
  async function copy() {
    const success = await copyText(item.body);
    setManual(!success);
    setCopied(success);
    if (!success && field.current) { field.current.focus(); field.current.select(); }
    window.clearTimeout(reset.current);
    if (success) reset.current = window.setTimeout(() => setCopied(false), 2200);
  }
  return <li className={'prompt-row' + (expanded ? ' is-open' : '')}>
    <div className="prompt-row-head">
      <button type="button" className="prompt-toggle" aria-expanded={expanded} aria-controls={'prompt-' + item.id}
        aria-label={item.title} onClick={onToggle}>
        <span className="prompt-chevron" aria-hidden="true" />
        <span><strong>{item.title}</strong>{showCategory && <small>{item.category || '未分类'}</small>}</span>
      </button>
      <button type="button" className="button prompt-copy" aria-label={'复制 ' + item.title} onClick={() => void copy()}>
        <span aria-live="polite">{copied ? '已复制' : '复制'}</span></button>
    </div>
    <div id={'prompt-' + item.id} hidden={!expanded}>{expanded && <>
      <pre className="prompt-body">{item.body}</pre>
      <div className="prompt-row-actions">
        {confirming ? <><span>删除这条提示词？</span>
          <button type="button" className="button" disabled={busy} onClick={() => setConfirming(false)}>取消</button>
          <button type="button" className="button prompt-danger" disabled={busy} onClick={onDelete}>确认删除</button></>
          : <><button type="button" className="link-button" onClick={onEdit}>编辑</button>
            <PublishPrompt key={item.revision} item={item} />
            <button type="button" className="link-button" disabled={busy} onClick={() => setConfirming(true)}>删除…</button></>}
      </div>
    </>}</div>
    {!expanded && <p className="prompt-excerpt">{item.body.trimStart().slice(0, 180)}</p>}
    {manual && <label className="prompt-manual">正文已选中，可用系统的「复制」。
      <textarea ref={field} value={item.body} readOnly rows={3} onFocus={e => e.target.select()} /></label>}
  </li>;
}
