import { useRef, useState } from 'react';
import { copyText } from '../lib/clipboard';

export interface Notice {
  text: string;
  error?: boolean;
  backup?: string;
  action?: { label: string; run: () => void };
}

export function ActionNotice({ note, busy, close }: { note: Notice; busy: boolean; close: () => void }) {
  const path = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState('');
  async function copy() {
    if (!note.backup || !path.current) return;
    if (await copyText(note.backup)) setCopied('已复制');
    else { path.current?.select(); setCopied('路径已选中，可手动复制'); }
  }
  return <aside className="library-notice" aria-label="操作结果">
    <span role={note.error ? 'alert' : 'status'}>{note.text}</span>
    {note.backup && <label>原副本备份 <input ref={path} readOnly value={note.backup} onFocus={e => e.target.select()} />
      <button type="button" className="link-button" onClick={() => void copy()}>{copied || '复制路径'}</button></label>}
    {note.action && <button type="button" className="button" disabled={busy} onClick={note.action.run}>{note.action.label}</button>}
    <button type="button" className="link-button notice-close" aria-label="收起操作结果" onClick={close}>×</button>
  </aside>;
}
