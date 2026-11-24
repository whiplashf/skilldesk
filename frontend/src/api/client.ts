export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '未找到该 skill';
    }
    if (error.status === 0) {
      return '无法连接本地服务';
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return '未知错误';
}

type QueryValue = string | number | boolean | null | undefined;

/** Builds `/api/...` URLs; empty values are dropped so the backend sees only real filters. */
export function withQuery(path: string, params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    search.set(name, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function readFailureReason(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (typeof body !== 'object' || body === null) {
      return null;
    }
    const record = body as Record<string, unknown>;
    if (typeof record.detail === 'string' && record.detail !== '') {
      return record.detail;
    }
    const error = record.error;
    if (typeof error === 'object' && error !== null) {
      const message = (error as Record<string, unknown>).message;
      if (typeof message === 'string' && message !== '') {
        return message;
      }
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * GET a JSON document from the local API.
 * Always uses a relative URL: dev goes through the Vite proxy, production is same-origin.
 */
export async function getJson<T>(path: string, signal?: AbortSignal, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      signal,
      ...options,
      headers: { accept: 'application/json', ...options?.headers },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError(0, '无法连接本地服务');
  }

  if (!response.ok) {
    const reason = await readFailureReason(response);
    throw new ApiError(response.status, reason ?? `请求失败（HTTP ${response.status}）`);
  }

  return (await response.json()) as T;
}

export async function writeJson<T>(path: string, method: string, body?: unknown, revision?: number): Promise<T> {
  const { token } = await getJson<{ token: string }>('/api/session');
  const headers: Record<string, string> = { 'X-Skilldesk-Token': token, 'Content-Type': 'application/json' };
  if (revision !== undefined) headers['If-Match'] = String(revision);
  return getJson<T>(path, undefined, { method, headers, body: JSON.stringify(body) });
}
