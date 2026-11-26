/** Response shapes of the local FastAPI server. */

export type ConfidenceValue = 'recorded' | 'declared' | 'claimed' | 'none';

export type IssueKind = 'dangling_link' | 'unclaimed_source' | 'duplicate_content';

export type SupportFileKind = 'markdown' | 'text' | 'image' | 'binary';

export interface Provenance {
  provider: string;
  sourceLabel: string;
  host: string;
  repo: string;
  path: string;
  ref: string;
  confidence: ConfidenceValue;
  evidence: string;
  localRoot: string;
  label: string;
}

export interface GitHubSource { repo: string; path: string }
export interface VersionStatus {
  status: 'release' | 'changed' | 'current' | 'baseline' | 'unknown';
  checkedAt: number;
  installed: string;
  latest: string;
  url: string;
  detail: string;
}
export interface UpstreamQuota {
  available: boolean;
  mode: 'token' | 'anonymous';
  source: '' | 'env' | 'config' | 'gh';
  limit?: number;
  remaining?: number;
  reset?: number;
  checkedAt?: number;
  detail?: string;
}
export interface AISettings {
  baseUrl: string; model: string; hasKey: boolean; enabled: boolean;
  baseFromEnv: boolean; modelFromEnv: boolean; keyFromEnv: boolean;
}
export interface AssetChanges { favorite?: boolean; mine?: boolean; github?: GitHubSource | null; category?: string | null }

export interface SkillCategory { key: string; name: string }
export interface CategoryGroup extends SkillCategory { count: number }

export interface PromptText { title: string; category: string; body: string }
export interface SavedPrompt extends PromptText { id: string; revision: number; updatedAt: number }

export interface SkillSummary {
  category: SkillCategory & { manual: boolean };
  repository: Repository;
  access: { agent: string; scope: string }[];
  favorite: boolean;
  mine: boolean;
  hasTrackingOverride: boolean;
  upstream: (GitHubSource & { ref: string }) | null;
  versionStatus: VersionStatus | null;
  libraryRevision: number;
  identity_key: string;
  name: string;
  dir_name: string;
  description: string;
  license: string;
  content_hash: string;
  bytes: number;
  lines: number;
  mtime: number;
  realpath: string;
  primary_kind: string;
  host_kinds: string[];
  placement_count: number;
  health: string[];
  provenance: Provenance;
}

export type PlacementAction = 'update' | 'uninstall' | 'unlink';
export type MaintenanceAction = 'install' | PlacementAction;

export interface MaintenancePreview {
  outcome?: 'current' | 'record';
  dangling?: boolean;
  id: string;
  action: MaintenanceAction;
  target: string;
  source: { host: string; repo: string; path: string } | null;
  commit: string;
  backup: string;
  license: string;
  expiresAt: number;
  localState: 'clean' | 'modified' | 'unknown';
  links: string[];
  linkTarget: string;
  changes: { added: string[]; changed: string[]; removed: string[] };
  files: number;
  bytes: number;
  scripts: string[];
}

export interface MaintenanceResult { action: MaintenanceAction; target: string; backup: string; outcome?: 'record' }

export interface Placement {
  installedSource: MaintenancePreview['source'];
  actions: PlacementAction[];
  managementNote: string;
  host_root: string;
  kind: string;
  entry: string;
  entry_path: string;
  realpath: string;
  is_symlink: boolean;
}

export interface Issue {
  name: string;
  location: string;
  missingTarget?: string;
  agents: string[];
  id: string;
  kind: IssueKind;
  /** Empty for issues that are not attached to a skill (dangling links). */
  identity_key: string;
  target: string;
  detail: string;
  fixable: boolean;
}

export interface SkillDetail extends SkillSummary {
  categoryOptions: SkillCategory[];
  placements: Placement[];
  issues: Issue[];
  frontmatter: Record<string, unknown>;
  html: string;
  confidenceLabel: string;
}

export interface SupportFile {
  rel: string;
  name: string;
  size: number;
  kind: SupportFileKind;
}

export interface FileContent {
  rel: string;
  name: string;
  size: number;
  kind: SupportFileKind;
  path: string;
  /** Present for markdown files only. */
  html?: string;
  /** Present for text files only. */
  text?: string;
  /** Present for images only: relative path of the raw asset endpoint. */
  url?: string;
}

export interface Facet {
  value: string;
  label?: string;
  count: number;
}

export interface Facets {
  agents: Facet[];
  hosts: Facet[];
  sources: Facet[];
  confidence: Facet[];
  health: Facet[];
  confidenceLabels: Record<string, string>;
  healthLabels: Record<string, string>;
}

export interface Repository {
  key: string;
  name: string;
  location: string;
}

export interface RepositoryGroup extends Repository {
  count: number;
  page?: number;
}

export interface IndexResponse {
  categories: CategoryGroup[];
  pendingCategories: number;
  hasFavorites?: boolean;
  items: SkillSummary[];
  total: number;
  limit: number;
  offset: number;
  repositories?: RepositoryGroup[];
}

/** `meta` numbers are serialised as strings by the server. */
export interface HealthMeta {
  generation: string;
  schema: string;
  version: string;
  scanned_at: string;
  skills: string;
  placements: string;
  dangling: string;
  issues: string;
  lockfile_entries: string;
}

export interface HealthCounts {
  skills: number;
  placements: number;
  dangling: number;
  unclaimed: number;
  issues: number;
  roots: number;
}

export interface Health {
  ok: boolean;
  version: string;
  meta: HealthMeta;
  counts: HealthCounts;
}

export interface IssueKindMeta {
  label: string;
  severity: string;
  fixable: boolean;
  description: string;
}

export interface IssuesResponse {
  counts: HealthCounts;
  total: number;
  items: Issue[];
  kinds: Partial<Record<IssueKind, IssueKindMeta>>;
}

export interface HostRoot {
  path: string;
  kind: string;
  label: string;
  priority: number;
  exists: boolean;
  entries: number;
}

export interface RootsResponse {
  items: HostRoot[];
}

export interface FilesResponse {
  items: SupportFile[];
}
