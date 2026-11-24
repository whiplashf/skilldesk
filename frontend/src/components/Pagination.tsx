import { pageCount } from '../lib/format';

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pages = pageCount(total, pageSize);

  return (
    <nav className="pager" aria-label="分页">
      <button
        type="button"
        className="button button--ghost"
        disabled={page <= 0}
        onClick={() => {
          onPageChange(page - 1);
        }}
      >
        上一页
      </button>
      <span className="pager-state">
        第 <span className="mono">{page + 1}</span> / <span className="mono">{pages}</span> 页
      </span>
      <button
        type="button"
        className="button button--ghost"
        disabled={page >= pages - 1}
        onClick={() => {
          onPageChange(page + 1);
        }}
      >
        下一页
      </button>
    </nav>
  );
}
