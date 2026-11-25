# Changelog

## 未发布 · 本机技能库

- 修复：经本机反向代理（authgate 等）访问时一律被「仅允许本机访问」拦掉。新增 `SKILLDESK_TRUSTED_PROXY=1`：只有**回环对端**转发的请求才放行公网 Host，直连远程依旧拒绝；写操作仍要会话令牌。
- 修复：shell 里形态异常的代理变量（实测 `NO_PROXY` 含 `[::1]`）会让 httpx 在构造阶段抛 `InvalidURL`，AI 翻译与 GitHub 版本检查都直接失败。出站请求改为自行解析代理（`SKILLDESK_PROXY` > `HTTPS_PROXY` > `HTTP_PROXY`）、回环地址永不走代理、坏代理值降级为直连。
- 技能库采用绿色目录和并排阅读布局。「GitHub 引入」和「我写的」默认按来源仓库展示，支持组内分页和切换回平铺清单。
- 按可用 Agent、项目范围、GitHub 来源、个人归属和收藏筛选已安装的 skill。收藏与归属跨重建保存。
- 正文优先的桌面和窄屏阅读，支持文件内相对链接和可配置的 AI 中文翻译。
- 提供单项及本页 GitHub 版本检查。使用 skill 目录和安装基线区分新发布、内容变化和缺少证据。
- 扫描嵌套安装目录，区分同名项目条目，并可在设置管理项目扫描范围。

## 0.1.0 · M1

首个公开快照。产品从只读的 skill 浏览器重做成可写的 skill 资产台，M1 只做索引与只读库。

- `backend/skilldesk`：宿主根抽象（agents / claude / codex / opencode / 项目级，可配置）、按 realpath 去重的实体 + 落点模型、身份键（`src:` 上游身份 / `loc:` 落点指纹）、SQLite 索引（可删可重建）、健康检测（悬空软链 / 待认领来源 / 重复实体）、FastAPI 只读 API，`/api/health` 按 mtime 自动重建索引（3 秒节流）
- `frontend/`：Vite + React + TypeScript 只读库视图（库 / 跟踪 / 设置，hash 路由、facets、分页、深浅色、键盘导航、支持文件查看器），构建产物 262 kB JS + 21 kB CSS
- CLI：`scan / list / show / health / doctor / serve / open`，查询命令全部支持 `--json`，`health` 有未处理项时退出码 2
- 来源分级：lockfile 记录 > skill 自身声明（`skill-release.json` / frontmatter）> 待认领。实测一台机器 133 个 skill：79 已记录、3 已声明、51 待认领；374 个落点收敛为 133 个实体；24 个悬空软链全部进入健康清单
- 76 个后端测试（identity / hosts / scan / health / index / server）+ ruff 检查
