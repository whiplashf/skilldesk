/** Response shapes of the local FastAPI server (verified against the live M1 build). */

export type ConfidenceValue = 'recorded' | 'declared' | 'none';

export type IssueKind = 'dangling_link' | 'unclaimed_source' | 'duplicate_content';

export type SupportFileKind = 'markdown' | 'text' | 'image' | 'binary';

export interface Provenance {
  host: string;
  repo: string;
  path: string;
  ref: string;
  confidence: ConfidenceValue;
  evidence: string;
  label: string;
}

export interface SkillSummary {
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

export interface Placement {
  host_root: string;
  kind: string;
  entry: string;
  entry_path: string;
  realpath: string;
  is_symlink: boolean;
}

export interface Issue {
  id: string;
  kind: IssueKind;
  /** Empty for issues that are not attached to a skill (dangling links). */
  identity_key: string;
  target: string;
  detail: string;
  fixable: boolean;
}

export interface SkillDetail extends SkillSummary {
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
  hosts: Facet[];
  sources: Facet[];
  confidence: Facet[];
  health: Facet[];
  confidenceLabels: Record<string, string>;
  healthLabels: Record<string, string>;
}

export interface IndexResponse {
  items: SkillSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** `meta` numbers are serialised as strings by the server. */
export interface HealthMeta {
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
