import { getJson, withQuery, writeJson } from './client';
import type { AISettings, AssetChanges, PromptText, SavedPrompt, SkillSummary, UpstreamQuota, VersionStatus } from './types';
import type {
  Facets,
  LibraryUpdateReport,
  MaintenancePreview,
  MaintenanceResult,
  PlacementAction,
  FileContent,
  FilesResponse,
  Health,
  IndexResponse,
  IssuesResponse,
  RootsResponse,
  SkillDetail,
} from './types';

export interface SkillQuery {
  category?: string;
  agent?: string;
  view?: string;
  layout?: 'flat' | 'sources';
  groupPages?: string;
  repository?: string;
  focus?: string;
  q?: string;
  host?: string;
  source?: string;
  confidence?: string;
  health?: string;
  limit: number;
  offset: number;
}

export const PAGE_SIZE = 50;

/** `identity_key` contains `:`, `/` and `@`, so it is always percent-encoded as one segment. */
function skillPath(identityKey: string): string {
  return `/api/skill/${encodeURIComponent(identityKey)}`;
}

export const api = {
  prompts: (signal?: AbortSignal) => getJson<{ items: SavedPrompt[]; catalogUrl?: string }>('/api/prompts', signal),
  savePrompt: (id: string, draft: PromptText, revision: number) =>
    writeJson<SavedPrompt>('/api/prompts/' + encodeURIComponent(id), 'PUT', draft, revision),
  deletePrompt: (item: SavedPrompt) =>
    writeJson<{ revision: number }>('/api/prompts/' + encodeURIComponent(item.id), 'DELETE', undefined, item.revision),
  installRoots: (signal: AbortSignal) =>
    getJson<{ items: { path: string; label: string }[] }>('/api/maintenance/roots', signal),
  previewInstall: (root: string, repository: string, path: string, signal?: AbortSignal) =>
    writeJson<MaintenancePreview>('/api/maintenance/install-preview', 'POST', { root, repository, path }, undefined, signal),
  previewPlacement: (identity_key: string, entry: string, action: PlacementAction) =>
    writeJson<MaintenancePreview>('/api/maintenance/placement-preview', 'POST', { identity_key, entry, action }),
  previewDangling: (entry: string) =>
    writeJson<MaintenancePreview>('/api/maintenance/dangling-preview', 'POST', { entry }),
  confirm: (id: string, accept_license: boolean, accept_local: boolean) =>
    writeJson<MaintenanceResult>('/api/maintenance/confirm', 'POST', { id, accept_license, accept_local }),
  projects: (signal: AbortSignal) => getJson<{ saved: string[]; effective: string[] }>('/api/projects', signal),
  changeProject: (path: string, remove = false) => writeJson('/api/projects', 'POST', { path, remove }),
  rescan: () => writeJson<Health>('/api/scan', 'POST'),
  patch: (item: SkillSummary, changes: AssetChanges) =>
    writeJson<SkillSummary>('/api/assets/' + encodeURIComponent(item.identity_key), 'PATCH', changes, item.libraryRevision),
  translate: (key: string) => writeJson<{ html: string; cached: boolean }>('/api/ai/translate', 'POST', { identity_key: key }),
  classify: () => writeJson<{ classified: number; remaining: number }>('/api/ai/classify', 'POST'),
  checkVersion: (key: string) => writeJson<VersionStatus>('/api/check', 'POST', { identity_key: key, force: true }),
  checkAll: (signal: AbortSignal) =>
    writeJson<LibraryUpdateReport>('/api/check-all', 'POST', undefined, undefined, signal),
  globalCheckStatus: (signal: AbortSignal) => getJson<LibraryUpdateReport | null>('/api/check-all', signal),
  aiSettings: (signal: AbortSignal) => getJson<AISettings>('/api/settings/ai', signal),
  upstreamQuota: (signal: AbortSignal) => getJson<UpstreamQuota>('/api/upstream/quota', signal),
  saveAI: (body: {baseUrl: string; model: string; apiKey?: string}) => writeJson<AISettings>('/api/settings/ai', 'PUT', body),
  health: (signal: AbortSignal): Promise<Health> => getJson<Health>('/api/health', signal),

  facets: (signal: AbortSignal): Promise<Facets> => getJson<Facets>('/api/facets', signal),

  index: (query: SkillQuery, signal: AbortSignal): Promise<IndexResponse> =>
    getJson<IndexResponse>(
      withQuery('/api/index', {
        category: query.category,
        agent: query.agent,
        view: query.view,
        layout: query.layout,
        group_pages: query.groupPages,
        repository: query.repository,
        focus: query.focus,
        q: query.q,
        host: query.host,
        source: query.source,
        confidence: query.confidence,
        health: query.health,
        limit: query.limit,
        offset: query.offset,
      }),
      signal,
    ),

  skill: (identityKey: string, signal?: AbortSignal): Promise<SkillDetail> =>
    getJson<SkillDetail>(skillPath(identityKey), signal),

  files: (identityKey: string, signal: AbortSignal): Promise<FilesResponse> =>
    getJson<FilesResponse>(`${skillPath(identityKey)}/files`, signal),

  file: (identityKey: string, rel: string, signal: AbortSignal, raw?: boolean): Promise<FileContent> =>
    getJson<FileContent>(withQuery(`${skillPath(identityKey)}/file`, { rel, raw }), signal),

  issues: (signal: AbortSignal): Promise<IssuesResponse> =>
    getJson<IssuesResponse>(withQuery('/api/issues', { limit: 500 }), signal),

  roots: (signal: AbortSignal): Promise<RootsResponse> => getJson<RootsResponse>('/api/roots', signal),
};
