import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { MaintenancePreview as Plan, MaintenanceResult } from '../api/types';
import { formatBytes } from '../lib/format';

export const actionLabel = { install: '安装', update: '升级', uninstall: '卸载', unlink: '解除链接' };

function Paths({ title, paths }: { title: string; paths: string[] }) {
  if (!paths.length) return null;
  return <details className="plan-files"><summary>{title} · {paths.length}</summary>
    <ul>{paths.map(path => <li key={path}><code>{path}</code></li>)}</ul></details>;
}

export function MaintenancePreview({ plan, onClose, onApplied }: {
  plan: Plan; onClose: () => void; onApplied: (result: MaintenanceResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [license, setLicense] = useState(false);
  const [local, setLocal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState('');
  const incoming = plan.action === 'install' || plan.action === 'update';
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  async function confirm() {
    if (busy) return;
    setBusy(true); setError('');
    try { onApplied(await api.confirm(plan.id, license, local)); }
    catch (err) {
      setError(describeError(err));
      setStale(err instanceof ApiError && (err.status === 409 || err.status === 410));
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="maintenance-dialog" aria-labelledby={title}
    onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id={title}>{actionLabel[plan.action]}预览</h2>
      <button type="button" className="link-button" disabled={busy} onClick={onClose}>关闭</button></header>
    <dl><dt>选中的安装位置</dt><dd><code>{plan.target}</code></dd>
      {plan.backup && <><dt>原副本备份到</dt><dd><code>{plan.backup}</code></dd></>}
      {plan.linkTarget && <><dt>保留的源目录</dt><dd><code>{plan.linkTarget}</code></dd></>}
      {plan.source && <><dt>来源</dt><dd>{plan.source.host}/{plan.source.repo}<br /><code>{plan.source.path}</code></dd>
        <dt>将安装的提交</dt><dd><code>{plan.commit}</code></dd>
        <dt>包内容</dt><dd>{plan.files} 个文件 · {formatBytes(plan.bytes)} · 许可证 {plan.license || '未声明'}</dd></>}
    </dl>
    {plan.action === 'unlink' && <p>此操作只解除该入口与源目录的链接。</p>}
    <Paths title="新增" paths={plan.changes.added} /><Paths title="修改" paths={plan.changes.changed} />
    <Paths title="移出" paths={plan.changes.removed} /><Paths title="随包脚本" paths={plan.scripts} />
    <Paths title="将使用新副本的关联入口" paths={plan.links} />
    {incoming && !plan.license && <label className="check-field"><input type="checkbox" checked={license}
      onChange={e => setLicense(e.target.checked)} />我已了解上游没有声明许可证</label>}
    {plan.localState !== 'clean' && <label className="check-field"><input type="checkbox" checked={local}
      onChange={e => setLocal(e.target.checked)} />{plan.localState === 'modified'
        ? '此副本有本地修改，我已查看变更并同意继续' : '缺少安装时的文件指纹，我已核对这一份本地副本'}</label>}
    {error && <p className="action-message" role="alert">{error}</p>}
    <footer><button type="button" className="button" disabled={busy} onClick={onClose}>{stale ? '返回重新预览' : '取消'}</button>
      <button type="button" className="button plan-confirm"
        disabled={stale || busy || (incoming && !plan.license && !license) || (plan.localState !== 'clean' && !local)}
        onClick={() => void confirm()}>{busy ? '正在处理…' : '确认' + actionLabel[plan.action]}</button></footer>
  </dialog>;
}
