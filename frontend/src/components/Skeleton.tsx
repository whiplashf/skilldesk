export interface SkeletonProps {
  width?: string | number;
  height?: number;
}

export function Skeleton({ width = '100%', height = 12 }: SkeletonProps) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />;
}

export interface ListSkeletonProps {
  rows?: number;
}

export function ListSkeleton({ rows = 8 }: ListSkeletonProps) {
  return (
    <div className="rows rows--skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div className="row row--skeleton" key={index}>
          <div className="row-top">
            <Skeleton width="38%" height={13} />
            <Skeleton width={52} height={13} />
          </div>
          <Skeleton height={10} />
          <Skeleton width="74%" height={10} />
          <div className="row-foot">
            <Skeleton width={132} height={10} />
            <Skeleton width={58} height={10} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="detail-skeleton" aria-hidden="true">
      <Skeleton width="44%" height={22} />
      <Skeleton width="26%" height={11} />
      <div className="skeleton-inline">
        <Skeleton width={72} height={18} />
        <Skeleton width={64} height={18} />
      </div>
      <Skeleton height={11} />
      <Skeleton width="88%" height={11} />
      <Skeleton width="62%" height={11} />
      <div className="skeleton-section">
        <Skeleton width="24%" height={11} />
        <Skeleton height={10} />
        <Skeleton width="72%" height={10} />
      </div>
      <div className="skeleton-section">
        <Skeleton width="18%" height={11} />
        <Skeleton height={10} />
        <Skeleton width="54%" height={10} />
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: ListSkeletonProps) {
  return (
    <div className="table-skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div className="table-skeleton-row" key={index}>
          <Skeleton width="18%" height={10} />
          <Skeleton width="46%" height={10} />
          <Skeleton width="12%" height={10} />
        </div>
      ))}
    </div>
  );
}
