import { useState } from 'react';
import type { UpdatePlan } from '../api/types';
import { api } from '../api/endpoints';
import { formatCount } from '../lib/format';

export interface UpdateDialogProps {
  plan: UpdatePlan;
  identityKey: string;
  onClose: () => void;
  onDone: (message: string) => void;
}

function FileList({ title, paths, tone }: { title: string; paths: string[]; tone: string }) {
  if (paths.length === 0) return null;
  return (
    <div className={`update-group update-group--${tone}`}>
      <span className="update-group-title">
        {title} {formatCount(paths.length)}
      </span>
      <ul className="dialog-files mono">
        {paths.map((path) => (
          <li key={path}>
            <span>{path}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Preview of an upgrade: what changes, what is at risk, and the backup guarantee. */
export function UpdateDialog({ plan, identityKey, onClose, onDone }: UpdateDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [allowDrift, setAllowDrift] = useState(false);
  const [ackLicense, setAckLicense] = useState(false);
  const blocked = (plan.localDrift && !allowDrift) || (plan.license === '' && !ackLicense);

  async function confirm() {
    setBusy(true);
    setError('');
    try {
      const result = await api.applyUpdate(identityKey, plan.planId, {
        allowDrift,
        acknowledgeLicense: ackLicense,
      });
      onDone(
        `已升级 ${result.name} 到 ${result.commit.slice(0, 8)}（旧版本备份在 ${'backup' in result ? String(result.backup) : '缓存目录'}）`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="升级预览">
      <div className="dialog">
        <header className="dialog-head">
          <h2>升级预览 · {plan.name}</h2>
          <button type="button" className="link-button" onClick={onClose} aria-label="关闭">×</button>
        </header>

        <p className="block-note mono">
          {plan.fromKnown && plan.from && plan.from !== plan.to
            ? `${plan.from.slice(0, 8)} → ${plan.to.slice(0, 8)}`
            : `上游提交 ${plan.to.slice(0, 8)}`}
          {plan.fromKnown && plan.from === plan.to ? '（本地副本与这个提交的内容有差异）' : ''} ·{' '}
          {plan.host}/{plan.repo} · {plan.license || '许可证未知'}
        </p>

        {plan.diff.identical ? (
          <p className="block-note">与已安装内容一致，这次升级不会有任何变化。</p>
        ) : (
          <>
            <FileList title="新增" paths={plan.diff.added} tone="added" />
            <FileList title="修改" paths={plan.diff.updated} tone="updated" />
            <FileList title="删除" paths={plan.diff.removed} tone="removed" />
            <p className="block-note">未变动的文件 {formatCount(plan.diff.unchanged)} 个。</p>
          </>
        )}

        <p className="block-note">旧版本会先备份到本地缓存目录，失败不会留下半套文件。</p>

        {plan.scripts.length > 0 && (
          <div className="dialog-warn">
            包含 {plan.scripts.length} 个脚本文件（不会被自动执行）：<span className="mono"> {plan.scripts.join('、')}</span>
          </div>
        )}

        {plan.warnings.length > 0 && (
          <ul className="dialog-warnings">
            {plan.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}

        <div className="dialog-checks">
          {plan.localDrift && (
            <label>
              <input type="checkbox" checked={allowDrift} onChange={(event) => setAllowDrift(event.target.checked)} />
              本地副本被改动过，我确认用上游内容覆盖它（旧内容在备份里）
            </label>
          )}
          {plan.license === '' && (
            <label>
              <input type="checkbox" checked={ackLicense} onChange={(event) => setAckLicense(event.target.checked)} />
              许可证无法识别，我确认继续
            </label>
          )}
        </div>

        {error && <p className="action-message" role="alert">{error}</p>}

        <footer className="dialog-foot">
          <button type="button" className="button button--ghost" onClick={onClose}>取消</button>
          <button type="button" className="button" disabled={blocked || busy} onClick={() => void confirm()}>
            {busy ? '升级中…' : '确认升级'}
          </button>
        </footer>
      </div>
    </div>
  );
}
