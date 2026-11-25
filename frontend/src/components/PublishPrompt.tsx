import { useRef, useState } from 'react';
import { describeError } from '../api/client';
import { api } from '../api/endpoints';
import type { PromptPublication, SavedPrompt } from '../api/types';

export function PublishPrompt({ item }: { item: SavedPrompt }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const attempt = useRef(0);
  const [preview, setPreview] = useState<PromptPublication>();
  const [step, setStep] = useState<'loading' | 'review' | 'sending' | 'done' | 'error'>('loading');
  const [error, setError] = useState('');

  async function check() {
    const token = ++attempt.current;
    setStep('loading'); setPreview(undefined); setError('');
    dialog.current?.showModal();
    try {
      const result = await api.previewPromptPublication(item);
      if (token === attempt.current) { setPreview(result); setStep('review'); }
    } catch (err) {
      if (token === attempt.current) { setError(describeError(err)); setStep('error'); }
    }
  }

  async function publish() {
    if (!preview || step !== 'review') return;
    setStep('sending');
    try {
      setPreview(await api.publishPrompt(item, preview.base));
      setStep('done');
    } catch (err) {
      setError(describeError(err)); setStep('error');
    }
  }

  const current = preview?.state === 'current';
  return <>
    <button type="button" className="link-button" onClick={() => void check()}>发布到 GitHub</button>
    <dialog ref={dialog} className="prompt-dialog" aria-label="发布到 GitHub"
      onCancel={event => { if (step === 'sending') event.preventDefault(); }}
      onClose={() => { attempt.current++; }}>
      <div className="prompt-form prompt-publication">
        <h2>{step === 'done' ? '已发布到 GitHub' : current ? '与 GitHub 一致' : '发布到 GitHub'}</h2>
        <p><strong>{item.title}</strong><br /><span>{item.category || '未分类'}</span></p>
        {step === 'loading' && <p role="status">正在核对 GitHub 上的版本…</p>}
        {preview && <p>目标仓库 <strong>{preview.repository}</strong> · {preview.branch}</p>}
        {step === 'review' && !current && <>
          <p>{preview?.state === 'update' ? '确认后将更新这条提示词的公开版本。' : '确认后，任何人都可以看到这条提示词的标题、分类和正文。'}</p>
          <details><summary>查看将发布的正文</summary><pre>{item.body}</pre></details>
          {preview?.previous && <details><summary>对照 GitHub 上的版本</summary>
            <p>{preview.previous.title} · {preview.previous.category || '未分类'}</p><pre>{preview.previous.body}</pre></details>}
        </>}
        {step === 'sending' && <p role="status">正在发布…</p>}
        {step === 'error' && <p role="alert">{error}</p>}
        <div className="prompt-form-actions">
          <button type="button" className="button" disabled={step === 'sending'} onClick={() => dialog.current?.close()}>
            {current || step === 'error' ? '关闭' : '取消'}</button>
          {current && <a className="button prompt-primary" href={preview.url} target="_blank" rel="noreferrer">在 GitHub 查看 ↗</a>}
          {step === 'error' && <button type="button" className="button" onClick={() => void check()}>重新核对</button>}
          {step === 'review' && !current && <button type="button" className="button prompt-primary" onClick={() => void publish()}>确认发布</button>}
        </div>
      </div>
    </dialog>
  </>;
}
