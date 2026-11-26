import { useEffect, useRef, useState } from 'react';
import { describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { LibraryUpdateReport, MaintenanceResult } from '../api/types';
import { formatDateTime, toIsoString } from '../lib/format';
import { VERSION_LABELS } from '../lib/labels';
import { skillHash } from '../lib/route';
import { ReleaseUpdate } from './ReleaseUpdate';
import { ReleaseNotes } from './ReleaseNotes';
import { Badge } from './Badge';

type Applied = (result: MaintenanceResult) => void;

function Results({ report, close, onApplied }: { report: LibraryUpdateReport; close: () => void; onApplied: Applied }) {
  const { total, checked, updates, failures, running } = report;
  const attempted = checked + failures.length;
  const remaining = total === null ? 0 : total - attempted;
  let headline = '全库检查结果';
  if (running) headline = '正在检查全库…';
  else if (updates.length) headline = updates.length + ' 个技能有更新';
  else if (total === 0) headline = '没有可检查的技能';
  else if (total === checked && !report.uncertain && !report.error) headline = '未发现新的正式版';

  return <>
    <h3 aria-live="polite">{headline}</h3>
    {total !== null && total > 0 && <p className="update-counts">
      已检查 {checked} / {total} 项
      {report.noRelease > 0 && ' · ' + report.noRelease + ' 项暂无正式版'}
      {report.uncertain > 0 && ' · ' + report.uncertain + ' 项待确认版本'}
      {failures.length > 0 && ' · ' + failures.length + ' 项失败'}
      {!running && remaining > 0 && ' · ' + remaining + ' 项尚未检查'}
    </p>}
    {running && total !== null && total > 0 && <progress aria-label="全库检查进度" value={attempted} max={total} />}
    {report.error && <p className="update-error" role="alert">{report.error}</p>}
    {updates.length > 0 && <ul className="update-list">{updates.map(item => <li key={item.key}>
      <a href={skillHash(item.key)} onClick={close}>
        <span><strong>{item.name}</strong><small>{item.repo} · {item.path}</small></span>
        <Badge tone="ok">{VERSION_LABELS[item.status]}{item.latest && ' · ' + item.latest}</Badge>
      </a>
      <ReleaseNotes release={item.release} />
      {item.entries.length > 0 && <ReleaseUpdate identityKey={item.key} entries={item.entries} release={item.release} onApplied={onApplied} />}
    </li>)}</ul>}
    {failures.length > 0 && <details className="update-failures">
      <summary>查看 {failures.length} 项失败原因</summary>
      <ul>{failures.map(item => <li key={item.key}>
        <a href={skillHash(item.key)} onClick={close}>{item.name}</a> · {item.detail}
      </li>)}</ul>
    </details>}
    {report.untracked > 0 && <p className="update-footnote">{report.untracked} 个技能缺少可检查的 GitHub 来源，已跳过。</p>}
    {report.finishedAt > 0 && <time dateTime={toIsoString(report.finishedAt)}>检查于 {formatDateTime(report.finishedAt)}</time>}
  </>;
}

export function LibraryUpdates({ onChecked, onApplied, generation }: { onChecked: () => void; onApplied: Applied; generation: string }) {
  const [report, setReport] = useState<LibraryUpdateReport | null>(null);
  const [open, setOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [request, setRequest] = useState({ start: false });
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const resultButton = useRef<HTMLButtonElement>(null);
  const observedRun = useRef(false);
  const onFinished = useRef(onChecked);
  useEffect(() => { setRequest({ start: false }); }, [generation]);
  useEffect(() => { onFinished.current = onChecked; }, [onChecked]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    if (request.start) observedRun.current = true;
    async function read(start: boolean) {
      try {
        const data = start ? await api.checkAll(controller.signal) : await api.globalCheckStatus(controller.signal);
        if (controller.signal.aborted) return;
        setReport(data);
        setStarting(false);
        setError('');
        if (data?.running) {
          observedRun.current = true;
          timer = window.setTimeout(() => void read(false), 1000);
        } else if (observedRun.current) {
          observedRun.current = false;
          onFinished.current();
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setStarting(false);
        setError(describeError(err));
      }
    }
    void read(request.start);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [request]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!container.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);

  function close() {
    setOpen(false);
    (resultButton.current ?? trigger.current)?.focus();
  }

  return <div className="check-updates" ref={container} onKeyDown={e => {
    if (e.key === 'Escape' && open && !(e.target instanceof Element && e.target.closest('dialog'))) { e.preventDefault(); close(); }
  }}>
    <button className="button check-all" type="button" ref={trigger} disabled={starting || report?.running}
      title="检查本机所有已关联 GitHub 来源的技能" onClick={() => {
        setStarting(true); setOpen(true); setError(''); setRequest({ start: true });
      }}>{starting || report?.running ? '正在检查…' : '检查全部更新'}</button>
    {report && <button type="button" className="link-button check-results" ref={resultButton}
      aria-label="查看全库检查结果" aria-expanded={open} onClick={() => {
        setOpen(!open);
        if (!open && !starting) setRequest({ start: false });
      }}>{report.running ? '进度' : '结果'}{report.updates.length > 0 && ' · ' + report.updates.length}</button>}
    {open && <section className="update-panel" aria-label="全库版本检查">
      <header><h2>全库版本检查</h2><button type="button" className="link-button" onClick={close}>收起</button></header>
      {starting ? <p role="status">正在读取本机技能…</p> : report && <Results report={report} close={close} onApplied={onApplied} />}
      {error && <p className="update-error" role="alert">{error} <button type="button" className="link-button"
        onClick={() => setRequest({ start: false })}>重新读取结果</button></p>}
      {!starting && !report && !error && <p>尚未进行全库检查。</p>}
    </section>}
  </div>;
}
