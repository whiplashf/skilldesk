import { useEffect, useRef, useState } from 'react';
import { api } from '../api/endpoints';
import { ApiError, describeError } from '../api/client';
import type { MaintenanceResult } from '../api/types';
import { accessSummary, healthLabel, VERSION_LABELS } from '../lib/labels';
import { formatDateTime } from '../lib/format';
import { OriginEditor, type Save } from './OriginEditor';
import { TranslationForm } from './TranslationSettings';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { DetailSkeleton } from './Skeleton';
import { ProvenanceBlock } from './ProvenanceBlock';
import { PlacementsBlock } from './PlacementsBlock';
import { SkillBody, type DocumentTarget } from './SkillBody';
import { SupportFiles } from './SupportFiles';

interface Props {
  backHref: string;
  identityKey: string; generation: string; busy: boolean; onSave: Save;
  onMaintenance: (result: MaintenanceResult) => void;
  onFile: (target: DocumentTarget) => void; onVersion: () => void;
}

export function SkillDetail({ identityKey, generation, backHref, busy, onSave, onFile, onVersion, onMaintenance }: Props) {
  const detail = useApi(signal => api.skill(identityKey, signal), [identityKey, generation], true);
  const settings = useApi(api.aiSettings, [], true);
  const [showFiles, setShowFiles] = useState(false);
  const translateButton = useRef<HTMLButtonElement>(null);
  const active = useRef(false);
  const editingTranslation = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const [translation, setTranslation] = useState<{ hash: string; html: string }>();
  const [chinese, setChinese] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [translateError, setTranslateError] = useState('');
  const [configOpen, setConfigOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [versionError, setVersionError] = useState('');
  if (detail.state.status === 'loading') return <DetailSkeleton />;
  if (detail.state.status === 'error') return <div className="detail"><a href={backHref}>← 返回列表</a>
    <ErrorState message={detail.state.error} onRetry={detail.reload} /></div>;
  const item = detail.state.data;
  const status = item.versionStatus;
  const ai = settings.state.data;
  const copies = Array.from(new Map(item.placements.filter(p => p.installedSource).map(p => [p.realpath, p])).values());
  const different = copies.filter(p => p.installedSource && item.upstream &&
    (p.installedSource.host !== 'github.com' || p.installedSource.repo.toLowerCase() !== item.upstream.repo.toLowerCase()
      || p.installedSource.path !== item.upstream.path));
  const translated = translation?.hash === item.content_hash ? translation.html : undefined;
  const showChinese = chinese && translated !== undefined;
  function editTranslation(open: boolean) {
    editingTranslation.current = open;
    setConfigOpen(open);
    if (!open) translateButton.current?.focus({ preventScroll: true });
  }
  async function toggleTranslation() {
    setTranslateError('');
    if (translated !== undefined) { setChinese(!showChinese); return; }
    setTranslating(true);
    try {
      const result = await api.translate(identityKey);
      setTranslation({ hash: item.content_hash, html: result.html }); setChinese(true);
    } catch (error) {
      setTranslateError(describeError(error));
      if (error instanceof ApiError && error.status === 501) { settings.reload(); editTranslation(true); }
    }
    finally { setTranslating(false); }
  }
  async function checkVersion() {
    setChecking(true); setVersionError('');
    try { await api.checkVersion(identityKey); onVersion(); }
    catch (error) { setVersionError(describeError(error)); }
    finally { setChecking(false); }
  }
  return <article className="detail">
    <a className="detail-back" href={backHref}>← 返回列表</a>
    <header className="reader-heading">
      <div><p className="reader-repo" title={item.repository.location}><i className="folder-icon" aria-hidden="true" />{item.repository.name}</p>
        <h1 className="detail-name">{item.name}</h1>
        <p className="reader-access">{accessSummary(item.access)}</p></div>
      <button className="button star-action" type="button" aria-pressed={item.favorite} disabled={busy}
        onClick={() => void onSave(item, { favorite: !item.favorite })}>{item.favorite ? '★ 已收藏' : '☆ 收藏'}</button>
    </header>
    {item.upstream && <section className="reader-section">
      <div className="section-heading"><h2>GitHub 版本{!status && item.upstream.path && <small> · 尚未检查</small>}</h2>
        <button type="button" className="button" disabled={checking || !item.upstream.path} onClick={() => void checkVersion()}>
          {checking ? '正在检查…' : '检查版本'}</button></div>
      {new Set(item.placements.map(p => p.realpath)).size > 1 && <p className="block-note">
        此次比较使用 <code>{item.realpath}</code>。可在各安装位置预览对应副本的变更。</p>}
      {different.length > 0 && <div className="source-comparison">
        <p>跟踪来源 <strong>github.com/{item.upstream.repo}</strong> · <code>{item.upstream.path}</code></p>
        {different.map(p => <p key={p.realpath}>此副本安装自 <strong>{p.installedSource!.host}/{p.installedSource!.repo}</strong>
          {' · '}<code>{p.installedSource!.path}</code>。升级使用此安装来源。
          {copies.length > 1 && <small>{p.realpath}</small>}</p>)}</div>}
      {!copies.length && <p className="block-note">跟踪 {item.upstream.repo}。本机没有可用于升级的 Git 安装记录。</p>}
      {status ? <div className={versionError ? 'version-result is-stale' : 'version-result'}>
        {versionError ? <small>上次检查结果 · </small> : null}<strong>{VERSION_LABELS[status.status]}</strong>
        {(status.installed || status.latest) && <span className="mono">{[status.installed, status.latest].filter(Boolean).join(' → ')}</span>}
        <p>{status.detail} · {formatDateTime(status.checkedAt)}</p>
        {status.url && <a href={status.url} target="_blank" rel="noreferrer">查看 GitHub 发布说明</a>}</div>
        : !item.upstream.path && <p className="block-note">请在来源中补全仓库内的 SKILL.md 路径。</p>}
      {versionError && <p className="action-message" role="alert">{versionError}</p>}
    </section>}
    <details className="reader-fold"><summary>来源与可用范围</summary>
      <OriginEditor data={item} save={onSave} busy={busy} />
      <ProvenanceBlock provenance={item.provenance} confidenceLabel={item.confidenceLabel} />
      <PlacementsBlock placements={item.placements} identityKey={identityKey} onApplied={onMaintenance}
        differingCopies={new Set(different.map(p => p.realpath))} />
      {item.issues.map(issue => <p className="block-note" key={issue.id}>{healthLabel(issue.kind)} · {issue.detail}</p>)}
      <p className="block-note">许可证 {item.license || '未声明'} · {item.lines} 行 · {formatDateTime(item.mtime)}</p>
    </details>
    <section className="reader-body" aria-label="SKILL.md 正文">
      <div className="reader-toolbar"><button type="button" className="link-button mono"
        onClick={() => onFile({ rel: 'SKILL.md', raw: true })}>SKILL.md 源文件</button>
        <button ref={translateButton} type="button" className="button translate-action" disabled={translating || settings.state.status === 'loading'}
          aria-expanded={!ai?.enabled || configOpen ? configOpen : undefined} onClick={() => {
            if (configOpen) editTranslation(false);
            else if (translated !== undefined || ai?.enabled) void toggleTranslation();
            else if (settings.state.status === 'error') settings.reload();
            else editTranslation(true);
          }}>
          {translating ? '正在翻译…' : configOpen ? '收起翻译设置' : showChinese ? '查看原文' : translated !== undefined ? '查看中文译文'
            : ai ? (ai.enabled ? 'AI 翻译成中文' : '设置中文翻译') : settings.state.status === 'error' ? '重试读取翻译设置' : '正在读取翻译设置…'}
        </button></div>
      {settings.state.status === 'error' && <p role="alert">{settings.state.error}</p>}
      {translateError && <p className="action-message" role="alert">{translateError} {ai && !configOpen &&
        <button type="button" className="link-button" onClick={() => editTranslation(true)}>检查翻译设置</button>}</p>}
      {configOpen && ai && <TranslationForm current={ai} resume onSaved={saved => {
        if (!active.current) return;
        settings.reload();
        if (saved.enabled && editingTranslation.current) { editTranslation(false); void toggleTranslation(); }
      }} />}
      <SkillBody html={showChinese ? translated : item.html} identityKey={identityKey} onFile={onFile} />
    </section>
    <details className="reader-fold" onToggle={event => setShowFiles(event.currentTarget.open)}><summary>支持文件</summary>
      {showFiles && <SupportFiles identityKey={identityKey} generation={generation} onOpenFile={rel => onFile({ rel })} />}
    </details>
  </article>;
}
