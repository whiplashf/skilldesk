const BYTE_UNITS = ['B', 'KB', 'MB', 'GB'] as const;

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '—';
  }
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit] ?? 'B'}`;
}

function pad(value: number): string {
  return value.toString().padStart(2, '0');
}

function toEpochSeconds(value: number | string): number | null {
  const seconds = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  return seconds;
}

export function formatDateTime(value: number | string): string {
  const seconds = toEpochSeconds(value);
  if (seconds === null) {
    return '—';
  }
  const date = new Date(seconds * 1000);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** ISO timestamp for `<time dateTime>`, or undefined when the value is unusable. */
export function toIsoString(value: number | string): string | undefined {
  const seconds = toEpochSeconds(value);
  return seconds === null ? undefined : new Date(seconds * 1000).toISOString();
}

export function formatRelative(value: number | string): string {
  const seconds = toEpochSeconds(value);
  if (seconds === null) {
    return '—';
  }
  const diffMs = Date.now() - seconds * 1000;
  if (diffMs < 0) {
    return formatDateTime(seconds);
  }
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) {
    return '刚刚';
  }
  if (minutes < 60) {
    return `${minutes} 分钟前`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} 小时前`;
  }
  const days = Math.floor(hours / 24);
  if (days < 30) {
    return `${days} 天前`;
  }
  return formatDateTime(seconds);
}

export function formatCount(value: number): string {
  return value.toLocaleString('zh-CN');
}

export function pageCount(total: number, pageSize: number): number {
  if (total <= 0) {
    return 1;
  }
  return Math.max(1, Math.ceil(total / pageSize));
}

/** `github.com/mattpocock/skills` → `mattpocock/skills`; deeper hosts keep the last two segments. */
export function sourceTail(label: string): string {
  const parts = label.split('/').filter((part) => part.length > 0);
  if (parts.length <= 1) {
    return label;
  }
  return parts.length <= 3 ? parts.slice(1).join('/') : parts.slice(-2).join('/');
}

export function sourceHost(label: string): string {
  return label.split('/')[0] ?? '';
}
