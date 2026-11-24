export function DetailEmpty() {
  return (
    <div className="detail-empty">
      <p className="detail-empty-title">从左侧选择一个 skill</p>
      <p className="detail-empty-hint">选中后地址栏会记录当前详情，可以直接分享或刷新。</p>
      <dl className="keys">
        <div>
          <dt>
            <kbd>/</kbd>
          </dt>
          <dd>聚焦搜索</dd>
        </div>
        <div>
          <dt>
            <kbd>↑</kbd>
            <kbd>↓</kbd>
          </dt>
          <dd>在列表中移动</dd>
        </div>
        <div>
          <dt>
            <kbd>Enter</kbd>
          </dt>
          <dd>打开详情</dd>
        </div>
        <div>
          <dt>
            <kbd>Esc</kbd>
          </dt>
          <dd>关闭文件预览，再清空筛选</dd>
        </div>
      </dl>
    </div>
  );
}
