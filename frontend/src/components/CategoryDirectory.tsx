import { useEffect, useRef, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { CategoryGroup } from '../api/types';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { TranslationForm } from './TranslationSettings';

interface Props {
  groups: CategoryGroup[];
  selected: string;
  pending: number;
  onSelect: (key: string) => void;
  onRefresh: () => void;
}

function CategorySetup({ onClose, onReady }: { onClose: () => void; onReady: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const settings = useApi(api.aiSettings, []);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return <dialog className="maintenance-dialog" aria-labelledby="category-setup-title" ref={dialog}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><h2 id="category-setup-title">设置 AI 功能分类</h2>
      <button className="link-button" type="button" onClick={onClose}>关闭</button></header>
    {settings.state.status === 'ready' ? <TranslationForm current={settings.state.data} classify
      onSaved={saved => { if (saved.enabled && dialog.current?.open) onReady(); }} />
      : settings.state.status === 'error' ? <ErrorState message={settings.state.error} onRetry={settings.reload} />
      : <p role="status">正在读取 AI 设置…</p>}
  </dialog>;
}

export function CategoryDirectory({ groups, selected, pending, onSelect, onRefresh }: Props) {
  const [running, setRunning] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [setup, setSetup] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [errorStatus, setErrorStatus] = useState<number>();
  const active = useRef(false);
  const working = useRef(false);
  const stop = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; stop.current = true; };
  }, []);
  const all = groups.reduce((sum, group) => sum + group.count, 0);
  const options = [{ key: '', name: '全部功能', count: all }, ...groups];
  if (selected && !groups.some(group => group.key === selected)) options.push({ key: selected, name: '当前分类', count: 0 });

  async function classify() {
    if (working.current) return;
    working.current = true; stop.current = false;
    setRunning(true); setPausing(false); setErrorStatus(undefined); setFeedback('AI 正在按功能分类…');
    let done = 0;
    try {
      while (active.current && !stop.current) {
        const batch = await api.classify();
        if (!active.current) return;
        done += batch.classified;
        onRefresh();
        if (!batch.remaining) { setFeedback(done ? '已完成 ' + done + ' 项分类' : '所有 skill 均已分类'); break; }
        setFeedback('已完成 ' + done + ' 项，还有 ' + batch.remaining + ' 项待分类');
        if (stop.current) setFeedback('已暂停，已完成 ' + done + ' 项分类');
      }
    } catch (error) {
      if (!active.current) return;
      if (error instanceof ApiError && error.status === 501) { setSetup(true); setFeedback(''); }
      else { setErrorStatus(error instanceof ApiError ? error.status : 0); setFeedback(describeError(error)); }
      onRefresh();
    } finally {
      working.current = false;
      if (active.current) { setRunning(false); setPausing(false); }
    }
  }
  return <section className="category-panel" aria-label="功能分类">
    <div className="category-heading"><h3>功能分类</h3>
      <select aria-label="按功能筛选" value={selected} onChange={e => onSelect(e.target.value)}>
        {options.map(group => <option key={group.key} value={group.key}>{group.name}（{group.count}）</option>)}
      </select>
    </div>
    <div className="category-options" role="group" aria-label="按功能筛选">
      {options.map(group => <button type="button" key={group.key} aria-pressed={selected === group.key}
        onClick={() => onSelect(selected === group.key ? '' : group.key)}>
        <span>{group.name}</span><small>{group.count}</small></button>)}
    </div>
    {(pending > 0 || running) && <div className="category-actions">
      {running ? <button className="button" type="button" disabled={pausing} onClick={() => {
        stop.current = true; setPausing(true);
      }}>{pausing ? '将在本批完成后暂停' : '暂停分类'}</button>
        : <button type="button" className="button" title="将名称和简介发给 AI，没有简介时使用正文开头"
          onClick={() => void classify()}>AI 分类 · 全库 {pending} 项待处理</button>}
    </div>}
    {feedback && <div className="category-feedback"><span role={errorStatus === undefined ? 'status' : 'alert'}>{feedback}</span>
      {errorStatus === 502 && <button type="button" className="link-button" onClick={() => setSetup(true)}>检查 AI 设置</button>}
      {!running && <button type="button" className="link-button" aria-label="收起分类提示" onClick={() => setFeedback('')}>×</button>}
    </div>}
    {setup && <CategorySetup onClose={() => setSetup(false)} onReady={() => { setSetup(false); void classify(); }} />}
  </section>;
}
