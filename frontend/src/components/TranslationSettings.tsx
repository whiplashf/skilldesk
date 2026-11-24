import { useState } from 'react';
import { api } from '../api/endpoints';
import { describeError } from '../api/client';
import type { AISettings } from '../api/types';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';

function Form({ current, reload }: { current: AISettings; reload: () => void }) {
  const [baseUrl, setBaseUrl] = useState(current.baseUrl);
  const [model, setModel] = useState(current.model);
  const [key, setKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  return <form className="settings-form" onSubmit={async event => {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      await api.saveAI({ baseUrl, model, ...(clearKey || key ? { apiKey: clearKey ? '' : key } : {}) });
      setKey(''); setClearKey(false); setMessage('翻译设置已保存'); reload();
    } catch (error) { setMessage(describeError(error)); } finally { setBusy(false); }
  }}>
    <p className="block-note">点击正文的翻译按钮时，Skilldesk 会将正文中的文字发给这里配置的服务。译文缓存在本机。</p>
    <label>兼容 OpenAI 的服务地址{current.baseFromEnv && '（环境变量）'}<input type="url" disabled={current.baseFromEnv} value={baseUrl} placeholder="http://localhost:11434/v1"
      onChange={e => setBaseUrl(e.target.value)} /></label>
    <label>模型{current.modelFromEnv && '（环境变量）'}<input value={model} disabled={current.modelFromEnv} placeholder="服务中可用的模型名" onChange={e => setModel(e.target.value)} /></label>
    <label>API 密钥{current.keyFromEnv && '（环境变量）'}<input type="password" value={key} autoComplete="new-password" disabled={current.keyFromEnv || clearKey}
      placeholder={current.hasKey ? '已配置' : '本地服务可留空'} onChange={e => setKey(e.target.value)} /></label>
    {current.hasKey && !current.keyFromEnv && <label className="clear-key"><input type="checkbox" checked={clearKey}
      onChange={e => setClearKey(e.target.checked)} />清除已保存的密钥</label>}
    <div className="form-actions"><button className="button" disabled={busy}>保存翻译设置</button>
      <span role="status">{message}</span></div>
  </form>;
}

export function TranslationSettings() {
  const settings = useApi(api.aiSettings, [], true);
  return <section className="block"><h2 className="block-title">AI 翻译</h2>
    {settings.state.status === 'ready' ? <Form current={settings.state.data} reload={settings.reload} /> :
      settings.state.status === 'error' ? <ErrorState message={settings.state.error} onRetry={settings.reload} /> : <p>正在读取配置…</p>}
  </section>;
}
