import { useState } from 'react';
import type { InstallPlan } from '../api/types';
import { api } from '../api/endpoints';
import { formatCount } from '../lib/format';

export interface InstallDialogProps {
  plan: InstallPlan;
  onClose: () => void;
  onInstalled: (message: string) => void;
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Dry-run preview for one install: what will be written, under which license,
 * and which scripts are involved. Nothing is written until 确认安装 is pressed.
 */
export function InstallDialog({ plan, onClose, onInstalled }: InstallDialogProps) {
  const needsLicense = plan.license === '';
  const needsForce = plan.warnings.some((warning) => warning.startsWith('目标已存在'));
  const [ackLicense, setAckLicense] = useState(false);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const blocked = (needsLicense && !ackLicense) || (needsForce && !force);

  async function confirm() {
    setBusy(true);
    setError('');
    try {
      const result = await api.installPlan(plan.planId, { force, acknowledgeLicense: ackLicense });
      onInstalled(`已安装 ${result.name} → ${result.target}（${result.files} 个文件，来源提交 ${result.commit.slice(0, 8)}）`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="安装预览">
      <div className="dialog">
        <header className="dialog-head">
          <h2>安装预览 · {plan.name}</h2>
          <button type="button" className="link-button" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <table className="table table--kv">
          <tbody>
            <tr>
              <th scope="row">来源</th>
              <td className="mono break">
                {plan.host}/{plan.repo}
              </td>
            </tr>
            <tr>
              <th scope="row">仓库内路径</th>
              <td className="mono break">{plan.path}</td>
            </tr>
            <tr>
              <th scope="row">提交</th>
              <td className="mono">{plan.commit.slice(0, 12)}</td>
            </tr>
            <tr>
              <th scope="row">许可证</th>
              <td>{plan.license || <span className="warn-text">未声明</span>}</td>
            </tr>
            <tr>
              <th scope="row">将写入</th>
              <td className="mono break">{plan.target}</td>
            </tr>
            <tr>
              <th scope="row">文件</th>
              <td className="mono">
                {formatCount(plan.files.length)} 个 · {bytes(plan.totalBytes)}
              </td>
            </tr>
            {plan.links.length > 0 && (
              <tr>
                <th scope="row">同时建立软链</th>
                <td className="mono break">{plan.links.join('、')}</td>
              </tr>
            )}
          </tbody>
        </table>

        <details className="reader-fold" open={plan.files.length <= 12}>
          <summary>文件清单（{plan.files.length}）</summary>
          <ul className="dialog-files mono">
            {plan.files.map((file) => (
              <li key={file.path}>
                <span>{file.path}</span>
                <span>{bytes(file.size)}</span>
              </li>
            ))}
          </ul>
        </details>

        {plan.scripts.length > 0 && (
          <div className="dialog-warn">
            包含 {plan.scripts.length} 个脚本文件（不会被自动执行，但安装后 agent 可能调用）：
            <span className="mono"> {plan.scripts.join('、')}</span>
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
          {needsLicense && (
            <label>
              <input type="checkbox" checked={ackLicense} onChange={(event) => setAckLicense(event.target.checked)} />
              仓库未声明可识别的许可证，我确认继续安装
            </label>
          )}
          {needsForce && (
            <label>
              <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
              目标目录已存在，覆盖它
            </label>
          )}
        </div>

        {error && (
          <p className="action-message" role="alert">
            {error}
          </p>
        )}

        <footer className="dialog-foot">
          <button type="button" className="button button--ghost" onClick={onClose}>
            取消
          </button>
          <button type="button" className="button" disabled={blocked || busy} onClick={() => void confirm()}>
            {busy ? '安装中…' : '确认安装'}
          </button>
        </footer>
      </div>
    </div>
  );
}
