# Changelog

## 0.1.0 · M1

首个公开快照。产品从只读的 skill 浏览器重做成可写的 skill 资产台，M1 只做索引与只读库。

- `backend/skilldesk`：宿主根抽象（agents / claude / codex / opencode / 项目级，可配置）、按 realpath 去重的实体 + 落点模型、身份键（`src:` 上游身份 / `loc:` 落点指纹）、SQLite 索引（可删可重建）、健康检测（悬空软链 / 待认领来源 / 重复实体）、FastAPI 只读 API，`/api/health` 按 mtime 自动重建索引（3 秒节流）
- `frontend/`：Vite + React + TypeScript 只读库视图（库 / 跟踪 / 设置，hash 路由、facets、分页、深浅色、键盘导航、支持文件查看器），构建产物 262 kB JS + 21 kB CSS
- CLI：`scan / list / show / health / doctor / serve / open`，查询命令全部支持 `--json`，`health` 有未处理项时退出码 2
- 来源分级：lockfile 记录 > skill 自身声明（`skill-release.json` / frontmatter）> 待认领。实测一台机器 133 个 skill：79 已记录、3 已声明、51 待认领；374 个落点收敛为 133 个实体；24 个悬空软链全部进入健康清单
- 76 个后端测试（identity / hosts / scan / health / index / server）+ ruff 检查
