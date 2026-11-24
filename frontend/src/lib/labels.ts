import type { IssueKind, SupportFileKind } from '../api/types';

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'muted';

/** Host kinds are client product names, not copy to translate. */
const HOST_KIND_LABELS: Record<string, string> = {
  agents: 'Agents',
  claude: 'Claude Code',
  opencode: 'OpenCode',
  codex: 'Codex',
};

export function hostKindLabel(kind: string): string {
  return HOST_KIND_LABELS[kind] ?? kind;
}

/** Fallbacks mirror `/api/facets`; that payload stays the source of truth once it arrives. */
const CONFIDENCE_LABELS: Record<string, string> = {
  recorded: '已记录',
  declared: '已声明',
  none: '待认领',
};

const HEALTH_LABELS: Record<string, string> = {
  unclaimed_source: '待认领来源',
  dangling_link: '悬空软链',
  duplicate_content: '重复实体',
};

export function confidenceLabel(value: string, labels?: Record<string, string>): string {
  return labels?.[value] ?? CONFIDENCE_LABELS[value] ?? value;
}

export function healthLabel(value: string, labels?: Record<string, string>): string {
  return labels?.[value] ?? HEALTH_LABELS[value] ?? value;
}

export function confidenceTone(value: string): Tone {
  switch (value) {
    case 'recorded':
      return 'ok';
    case 'declared':
      return 'warn';
    default:
      return 'muted';
  }
}

export function healthTone(value: string): Tone {
  switch (value) {
    case 'unclaimed_source':
      return 'warn';
    case 'duplicate_content':
    case 'dangling_link':
      return 'danger';
    default:
      return 'neutral';
  }
}

const SEVERITY_LABELS: Record<string, string> = {
  error: '严重',
  warning: '警告',
  info: '提示',
};

export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] ?? severity;
}

export function severityTone(severity: string): Tone {
  switch (severity) {
    case 'error':
      return 'danger';
    case 'warning':
      return 'warn';
    default:
      return 'muted';
  }
}

/** Tracking groups render in product order, never in API order. */
export const ISSUE_KIND_ORDER: readonly IssueKind[] = [
  'dangling_link',
  'unclaimed_source',
  'duplicate_content',
];

const FILE_KIND_LABELS: Record<SupportFileKind, string> = {
  markdown: 'Markdown',
  text: '文本',
  image: '图片',
  binary: '二进制',
};

export function fileKindLabel(kind: SupportFileKind): string {
  return FILE_KIND_LABELS[kind];
}

export function accessSummary(access: { agent: string; scope: string }[]): string {
  const scopes = new Map<string, string[]>();
  for (const { agent, scope } of access) {
    const agents = scopes.get(scope) ?? [];
    agents.push(hostKindLabel(agent));
    scopes.set(scope, agents);
  }
  return Array.from(scopes, ([scope, agents]) => {
    const project = scope.split(/[\\/]/).filter(Boolean).pop();
    return agents.join('、') + (project ? ' · ' + project + ' 项目' : ' · 全局');
  }).join(' / ') || 'Agent 范围待确认';
}

export const VERSION_LABELS = {
  release: '有新版本',
  changed: '内容有变化',
  current: '已是最新',
  unknown: '待确认版本',
} as const;
