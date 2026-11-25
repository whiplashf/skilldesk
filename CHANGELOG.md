# Changelog

## 未发布 · 本机技能库

- 「可修复」不再是空标签：新增 `POST /api/issues/{id}/fix` 与跟踪页的 **修复 / 移除** 按钮。悬空软链优先重指到同名实体副本（store 优先），没有副本时可移除死链；非机械性问题（待认领来源、重复实体）明确拒绝并指向详情页的人工处理。修复后会重扫索引并回传最新计数，安全边界是：只动已登记宿主根里的软链、失败不触碰原链接。本机实测一次性修好 24 条历史遗留死链：悬空 24 → 0，落点 380 → 404（这 24 个 skill 现在对 Claude Code 也可用），问题总数 67 → 43。
- 版本检查不再被匿名配额卡死：凭据按 环境变量 `SKILLDESK_GITHUB_TOKEN` → `~/.config/skilldesk/upstream.json` 的 `{"githubToken": ...}` → 已登录的 `gh` CLI 依次解析（本机实测自动复用 gh 的 token，额度 60 → **5000 次/小时**）。新增 `GET /api/upstream/quota`，设置页「GitHub 检查」显示凭据来源、剩余额度与重置时间；额度用尽的 429 会直接写出恢复时间。另修一处误导：检查失败时不再把上一次的「已是最新」当成本次结果展示，而是标成「上次检查结果」。
- 版本检查有了真正的**安装基线**：新增 `backend/skilldesk/baselines.py`，首次检查时记录上游目录的 git tree SHA 与本地目录指纹（存 `~/.local/state/skilldesk/baselines.json`，删掉只丢历史不丢数据）。之后每次检查即可回答两件事：上游目录有没有变、本地副本有没有被手改（`localModified`，详情里会附一句说明）。
- 目录指纹改为「本地目录 vs 上游当前目录」直比，这台机器上 GitHub 来源的 51 个 skill 立刻从"待确认版本"变成可比对；没有可比记录时状态是新增的 **已记录基线**，而不是假装"已是最新"。
- 顺带修掉配额浪费：仓库级响应（HEAD、递归 tree、releases）按进程缓存，`force` 只绕过单个 skill 的结果缓存 —— 否则"检查本页 50 个"会花掉 150 次请求（匿名配额 60/小时）。索引 schema 升到 4，多存 `installedAt`（用于"安装后仓库无新提交"这种保守判断）。
- 修复：经本机反向代理（authgate 等）访问时一律被「仅允许本机访问」拦掉。新增 `SKILLDESK_TRUSTED_PROXY=1`：只有**回环对端**转发的请求才放行公网 Host，直连远程依旧拒绝；写操作仍要会话令牌。配套把 uvicorn 的 `proxy_headers` 关掉——否则它会把对端地址改写成 `X-Forwarded-For`，正是反向代理提供的那个值，拿它判断可信度等于没判断。
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
