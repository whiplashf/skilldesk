import { useMemo, useState } from 'react';
import type { InstallPlan, RegistryEntry, RegistryResponse } from '../api/types';
import { api } from '../api/endpoints';
import { Badge } from '../components/Badge';
import { ErrorState } from '../components/ErrorState';
import { InstallDialog } from '../components/InstallDialog';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { formatCount } from '../lib/format';
import { useApi } from '../lib/useApi';

export interface DiscoverPageProps {
  onInstalled: () => void;
}

interface ParsedSource {
  host: string;
  repo: string;
  path: string;
}

/**
 * Accepts what people actually paste: `owner/repo`, `owner/repo.git`, a GitHub
 * URL, or a URL pointing at a folder (`/tree/<branch>/skills/x`). When no path
 * is given the skill is assumed to sit at `SKILL.md` and the backend reports
 * that it cannot find it, which is clearer than guessing.
 */
function parseSource(value: string, fallbackPath: string): ParsedSource | null {
  const text = value.trim();
  if (!text) return null;
  const fallback = fallbackPath.trim().replace(/^\/+/, '');
  if (text.includes('://')) {
    let url: URL;
    try {
      url = new URL(text);
    } catch {
      return null;
    }
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length < 2) return null;
    const owner = parts[0] ?? '';
    const name = (parts[1] ?? '').replace(/\.git$/, '');
    const repo = `${owner}/${name}`;
    const treeIndex = parts.indexOf('tree');
    if (treeIndex >= 2) {
      const rest = parts.slice(treeIndex + 2);
      const path = rest.length > 0 ? rest.join('/') : '';
      return { host: url.hostname.toLowerCase(), repo, path: path ? (path.endsWith('SKILL.md') ? path : `${path}/SKILL.md`) : fallback || 'SKILL.md' };
    }
    return { host: url.hostname.toLowerCase(), repo, path: fallback || 'SKILL.md' };
  }
  const repo = text.replace(/\.git$/, '').replace(/^https?:\/\/[^/]+\//, '');
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) return null;
  return { host: 'github.com', repo, path: fallback || 'SKILL.md' };
}

function skillName(entry: RegistryEntry): string {
  const segments = entry.path.split('/');
  if (segments.length > 1) return segments[segments.length - 2] ?? entry.repo;
  return entry.repo.split('/')[1] ?? entry.repo;
}

function stateBadge(entry: RegistryEntry) {
  if (entry.state === 'installed') return <Badge tone="ok">已安装</Badge>;
  if (entry.state === 'registered') return <Badge tone="warn">已登记正文</Badge>;
  return <Badge tone="muted">未安装</Badge>;
}

function RegistryGroup({
  repo,
  entries,
  busy,
  versions,
  onPreview,
  onRegister,
  onCheck,
}: {
  repo: string;
  entries: RegistryEntry[];
  busy: string;
  versions: Record<string, string>;
  onPreview: (entry: RegistryEntry) => void;
  onRegister: (entry: RegistryEntry) => void;
  onCheck: (entry: RegistryEntry) => void;
}) {
  return (
    <section className="block">
      <h2 className="block-title">
        <span className="mono">{repo}</span> <span className="dim">{formatCount(entries.length)} 个 skill</span>
      </h2>
      <ul className="registry-rows">
        {entries.map((entry) => {
          const busyId = `${entry.host}:${entry.repo}@${entry.path}`;
          const running = busy === busyId;
          return (
            <li key={busyId} className="registry-row">
              <div className="registry-main">
                <span className="registry-name">{skillName(entry)}</span>
                {stateBadge(entry)}
                {entry.license ? <Badge tone="muted">{entry.license}</Badge> : <Badge tone="warn">许可证未知</Badge>}
                <span className="registry-path mono">{entry.path}</span>
              </div>
              {entry.description ? <p className="registry-desc">{entry.description}</p> : null}
              <div className="registry-actions">
                {entry.state === 'installed' ? (
                  <>
                    <button
                      type="button"
                      className="button button--small"
                      disabled={running || entry.identityKey === ''}
                      title="用本机安装基线对比上游当前目录"
                      onClick={() => onCheck(entry)}
                    >
                      {running ? '检查中…' : '检查上游版本'}
                    </button>
                    <button
                      type="button"
                      className="button button--small button--ghost"
                      disabled={running}
                      title="用清单里的上游版本重新安装（会覆盖现有副本）"
                      onClick={() => onPreview(entry)}
                    >
                      覆盖重装
                    </button>
                    {versions[entry.identityKey] ? (
                      <span className="chip chip--tag" title="版本检查结果">
                        {versions[entry.identityKey]}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="button button--small"
                      disabled={running}
                      onClick={() => onPreview(entry)}
                    >
                      {running ? '预览中…' : '预览并安装'}
                    </button>
                    <button
                      type="button"
                      className="button button--small button--ghost"
                      disabled={running || entry.state !== 'available'}
                      title="只缓存 SKILL.md 到本地，便于先阅读再决定是否安装"
                      onClick={() => onRegister(entry)}
                    >
                      登记正文
                    </button>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

type StateFilter = 'installable' | 'installed' | 'all';

const STATE_FILTERS: ReadonlyArray<{ id: StateFilter; label: string }> = [
  { id: 'installable', label: '可引入' },
  { id: 'installed', label: '已安装' },
  { id: 'all', label: '全部' },
];

function matchesFilter(entry: RegistryEntry, filter: StateFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'installed') return entry.state === 'installed';
  return entry.state !== 'installed';
}

export function DiscoverPage({ onInstalled }: DiscoverPageProps) {
  const registry = useApi<RegistryResponse>((signal) => api.registry(signal), []);
  const [input, setInput] = useState('');
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<InstallPlan | null>(null);
  const [filter, setFilter] = useState<StateFilter>('installable');
  const [versions, setVersions] = useState<Record<string, string>>({});

  const allEntries = registry.state.status === 'ready' ? registry.state.data.entries : [];
  const counts = {
    installable: allEntries.filter((entry) => matchesFilter(entry, 'installable')).length,
    installed: allEntries.filter((entry) => entry.state === 'installed').length,
    all: allEntries.length,
  };

  const groups = useMemo(() => {
    const items = (registry.state.status === 'ready' ? registry.state.data.entries : []).filter((entry) =>
      matchesFilter(entry, filter),
    );
    const byRepo = new Map<string, RegistryEntry[]>();
    for (const entry of items) {
      const key = `${entry.host}/${entry.repo}`;
      const bucket = byRepo.get(key) ?? [];
      bucket.push(entry);
      byRepo.set(key, bucket);
    }
    return [...byRepo.entries()].sort((left, right) => left[0].localeCompare(right[0]));
  }, [registry.state, filter]);

  const parsed = parseSource(input, pathInput);

  async function preview(target: { host: string; repo: string; path: string }) {
    setBusy(`${target.host}:${target.repo}@${target.path}`);
    setError('');
    try {
      setPlan(await api.planInstall(target));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy('');
    }
  }

  async function checkInstalled(entry: RegistryEntry) {
    if (!entry.identityKey) return;
    setBusy(`${entry.host}:${entry.repo}@${entry.path}`);
    setError('');
    try {
      const status = await api.checkVersion(entry.identityKey, true);
      const label =
        status.status === 'release'
          ? `有新版本${status.latest ? ` · ${status.latest}` : ''}`
          : status.status === 'changed'
            ? '上游内容有变化'
            : status.status === 'current'
              ? '已是最新'
              : status.status === 'baseline'
                ? '已记录基线'
                : '待确认版本';
      setVersions((current) => ({ ...current, [entry.identityKey]: label }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy('');
    }
  }

  async function register(target: { host: string; repo: string; path: string }) {
    setBusy(`${target.host}:${target.repo}@${target.path}`);
    setError('');
    try {
      const result = await api.importEntry(target);
      setNotice(result.imported ? `已登记并缓存 SKILL.md：${result.cached}` : `正文已是最新：${result.cached}`);
      registry.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="发现"
        sub="把还没有的 skill 引进来：从清单或任意 GitHub 仓库安装，安装前先给出预览（文件清单、许可证、脚本）。已安装的在这里只用于检查上游版本和覆盖重装。"
        aside={
          <button type="button" className="button button--ghost" onClick={registry.reload}>
            刷新清单
          </button>
        }
      />

      <section className="block">
        <h2 className="block-title">从链接导入</h2>
        <div className="import-row">
          <input
            className="import-input mono"
            aria-label="仓库或链接"
            placeholder="owner/repo 或 https://github.com/owner/repo/tree/main/skills/x"
            value={input}
            spellCheck={false}
            onChange={(event) => setInput(event.target.value)}
          />
          <input
            className="import-input mono"
            aria-label="SKILL.md 路径"
            placeholder="SKILL.md 路径（可留空，默认 SKILL.md）"
            value={pathInput}
            spellCheck={false}
            onChange={(event) => setPathInput(event.target.value)}
          />
          <button
            type="button"
            className="button"
            disabled={parsed === null || busy !== ''}
            onClick={() => {
              if (parsed) void preview(parsed);
            }}
          >
            预览安装
          </button>
          <button
            type="button"
            className="button button--ghost"
            disabled={parsed === null || busy !== ''}
            onClick={() => {
              if (parsed) void register(parsed);
            }}
          >
            只登记正文
          </button>
        </div>
        <p className="block-note">
          {parsed === null
            ? '支持 owner/repo、GitHub URL，或指向某个目录的 /tree/ 链接。'
            : `将检查 ${parsed.host}/${parsed.repo} 的 ${parsed.path}`}
        </p>
      </section>

      {notice ? (
        <p className="action-message" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="action-message" role="alert">
          {error}
        </p>
      ) : null}

      <div className="discover-filter" role="group" aria-label="按状态筛选">
        {STATE_FILTERS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={filter === option.id ? 'chip chip--active' : 'chip'}
            aria-pressed={filter === option.id}
            onClick={() => setFilter(option.id)}
          >
            {option.label} {formatCount(counts[option.id])}
          </button>
        ))}
      </div>

      {registry.state.status === 'loading' ? (
        <section className="block">
          <Skeleton width="180px" height={20} />
          <Skeleton width="100%" height={14} />
          <Skeleton width="92%" height={14} />
        </section>
      ) : registry.state.status === 'error' ? (
        <ErrorState title="清单加载失败" message={registry.state.error} onRetry={registry.reload} />
      ) : (
        <>
          {registry.state.data.errors.map((failure) => (
            <p className="block-note" key={failure.source}>
              清单 {failure.source} 读取失败：{failure.error}（{failure.path}）
            </p>
          ))}
          {groups.length === 0 ? (
            <p className="block-note">
              {filter === 'installable'
                ? '清单里的条目本机都已经装了。切到「已安装」可检查上游版本，或在上面粘贴新链接。'
                : '清单里还没有条目。可以在上面粘贴链接，或在设置里添加清单文件。'}
            </p>
          ) : (
            groups.map(([repo, entries]) => (
              <RegistryGroup
                key={repo}
                repo={repo}
                entries={entries}
                busy={busy}
                versions={versions}
                onPreview={(entry) => void preview({ host: entry.host, repo: entry.repo, path: entry.path })}
                onRegister={(entry) => void register({ host: entry.host, repo: entry.repo, path: entry.path })}
                onCheck={(entry) => void checkInstalled(entry)}
              />
            ))
          )}
        </>
      )}

      {plan ? (
        <InstallDialog
          plan={plan}
          onClose={() => setPlan(null)}
          onInstalled={(message) => {
            setPlan(null);
            setNotice(message);
            registry.reload();
            onInstalled();
          }}
        />
      ) : null}
    </div>
  );
}
