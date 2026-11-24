import { useEffect, useState } from 'react';
import { api } from '../api/endpoints';
import { ApiError, describeError } from '../api/client';
import type { AssetChanges, SkillDetail as Detail, SkillSummary } from '../api/types';
import { accessLabel, healthLabel, VERSION_LABELS } from '../lib/labels';
import { formatDateTime } from '../lib/format';
import { HASH, libraryHref } from '../lib/route';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { DetailSkeleton } from './Skeleton';
import { ProvenanceBlock } from './ProvenanceBlock';
import { PlacementsBlock } from './PlacementsBlock';
import { SkillBody, type DocumentTarget } from './SkillBody';
import { SupportFiles } from './SupportFiles';

type Save = (item: SkillSummary, changes: AssetChanges) => Promise<boolean>;

function OriginEditor({ data, save, busy }: { data: Detail; save: Save; busy: boolean }) {
  const [editing, setEditing] = useState(false);
  const [repo, setRepo] = useState('');
  const [path, setPath] = useState('');
  const [mine, setMine] = useState(data.mine);
  useEffect(() => setMine(data.mine), [data.mine]);
  return <div className="origin-editor">
    <label className="check-field"><input type="checkbox" checked={mine} disabled={busy}
      onChange={async event => {
        const selected = event.target.checked;
        setMine(selected);
        if (!await save(data, { mine: selected })) setMine(data.mine);
      }} /> 我写的</label>
    {data.upstream && <p className="source-coordinate">GitHub · {data.upstream.repo} / {data.upstream.path || '路径待确认'}</p>}
    {editing ? <form className="settings-form" onSubmit={async event => {
      event.preventDefault();
      if (await save(data, { github: { repo, path } })) setEditing(false);
    }}>
      <label>GitHub 仓库<input required placeholder="owner/repo" value={repo} onChange={e => setRepo(e.target.value)} /></label>
      <label>仓库内路径<input required placeholder="skills/example/SKILL.md" value={path} onChange={e => setPath(e.target.value)} /></label>
      <div className="form-actions"><button className="button" disabled={busy}>保存来源</button>
        <button type="button" className="button" onClick={() => setEditing(false)}>取消</button>
        <button type="button" className="link-button" disabled={busy} onClick={async () => {
          if (await save(data, { github: null })) setEditing(false);
        }}>恢复扫描来源</button></div>
    </form> : <button className="button" type="button" onClick={() => {
      setRepo(data.upstream?.repo ?? ''); setPath(data.upstream?.path || 'SKILL.md'); setEditing(true);
    }}>{data.upstream ? '编辑 GitHub 来源' : '关联 GitHub 来源'}</button>}
  </div>;
}

interface Props {
  identityKey: string; generation: string; busy: boolean; onSave: Save;
  onFile: (target: DocumentTarget) => void; onVersion: () => void;
}

export function SkillDetail({ identityKey, generation, busy, onSave, onFile, onVersion }: Props) {
  const detail = useApi(signal => api.skill(identityKey, signal), [identityKey, generation], true);
  const files = useApi(signal => api.files(identityKey, signal), [identityKey, generation], true);
  const [translation, setTranslation] = useState<{ hash: string; html: string }>();
  const [chinese, setChinese] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [translateError, setTranslateError] = useState('');
  const [needsConfig, setNeedsConfig] = useState(false);
  const [checking, setChecking] = useState(false);
  const [versionError, setVersionError] = useState('');
  if (detail.state.status === 'loading') return <DetailSkeleton />;
  if (detail.state.status === 'error') return <div className="detail"><a href={libraryHref()}>← 返回列表</a>
    <ErrorState message={detail.state.error} onRetry={detail.reload} /></div>;
  const item = detail.state.data;
  const status = item.versionStatus;
  const translated = translation?.hash === item.content_hash ? translation.html : undefined;
  const showChinese = chinese && translated !== undefined;
  async function toggleTranslation() {
    setTranslateError(''); setNeedsConfig(false);
    if (translated !== undefined) { setChinese(!showChinese); return; }
    setTranslating(true);
    try {
      const result = await api.translate(identityKey);
      setTranslation({ hash: item.content_hash, html: result.html }); setChinese(true);
    } catch (error) { setTranslateError(describeError(error)); setNeedsConfig(error instanceof ApiError && error.status === 501); }
    finally { setTranslating(false); }
  }
  async function checkVersion() {
    setChecking(true); setVersionError('');
    try { await api.checkVersion(identityKey, Boolean(status)); onVersion(); }
    catch (error) { setVersionError(describeError(error)); }
    finally { setChecking(false); }
  }
  return <article className="detail">
    <a className="detail-back" href={libraryHref()}>← 返回列表</a>
    <header className="reader-heading">
      <div><h1 className="detail-name">{item.name}</h1>
        <p className="reader-access">{item.access.map(accessLabel).join('、') || 'Agent 范围待确认'}</p></div>
      <button className="button star-action" type="button" aria-pressed={item.favorite} disabled={busy}
        onClick={() => void onSave(item, { favorite: !item.favorite })}>{item.favorite ? '★ 已收藏' : '☆ 收藏'}</button>
    </header>
    {item.upstream && <section className="reader-section">
      <div className="section-heading"><h2>GitHub 版本{!status && item.upstream.path && <small> · 尚未检查</small>}</h2>
        <button type="button" className="button" disabled={checking || !item.upstream.path} onClick={() => void checkVersion()}>
          {checking ? '正在检查…' : '检查版本'}</button></div>
      {status ? <div className="version-result"><strong>{VERSION_LABELS[status.status]}</strong>
        {(status.installed || status.latest) && <span className="mono">{[status.installed, status.latest].filter(Boolean).join(' → ')}</span>}
        <p>{status.detail} · {formatDateTime(status.checkedAt)}</p>
        {status.url && <a href={status.url} target="_blank" rel="noreferrer">查看 GitHub 发布说明</a>}</div>
        : !item.upstream.path && <p className="block-note">请在来源中补全仓库内的 SKILL.md 路径。</p>}
      {versionError && <p className="action-message" role="alert">{versionError}</p>}
    </section>}
    <details className="reader-fold"><summary>来源与可用范围</summary>
      <OriginEditor data={item} save={onSave} busy={busy} />
      <ProvenanceBlock provenance={item.provenance} confidenceLabel={item.confidenceLabel} />
      <PlacementsBlock placements={item.placements} />
      {item.issues.map(issue => <p className="block-note" key={issue.id}>{healthLabel(issue.kind)} · {issue.detail}</p>)}
      <p className="block-note">许可证 {item.license || '未声明'} · {item.lines} 行 · {formatDateTime(item.mtime)}</p>
    </details>
    <section className="reader-body" aria-label="SKILL.md 正文">
      <div className="reader-toolbar"><button type="button" className="link-button mono"
        onClick={() => onFile({ rel: 'SKILL.md', raw: true })}>SKILL.md 源文件</button>
        <button type="button" className="button translate-action" disabled={translating} onClick={() => void toggleTranslation()}>
          {translating ? '正在翻译…' : showChinese ? '查看原文' : translated !== undefined ? '查看中文译文' : 'AI 翻译成中文'}
        </button></div>
      {translateError && <p className="action-message" role="status">{translateError} {needsConfig && <a href={HASH.settings}>打开翻译设置</a>}</p>}
      <SkillBody html={showChinese ? translated : item.html} identityKey={identityKey} onFile={onFile} />
    </section>
    <details className="reader-fold"><summary>支持文件{files.state.status === 'ready' ? ' · ' + files.state.data.items.length : ''}</summary>
      <SupportFiles state={files.state} onOpenFile={rel => onFile({ rel })} onRetry={files.reload} />
    </details>
  </article>;
}
