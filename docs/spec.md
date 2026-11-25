# Skilldesk 设计规格

## 当前迭代 · 本机技能库

当前状态为实现完成、待用户验收。首页只呈现本机已安装的 skill。查看本机库与设置均可离线。用户可以在已安装项上检查 GitHub 版本、预览升级和翻译正文，也可以在设置手动输入仓库地址并预览安装。

| 场景 | 验收方式 |
| --- | --- |
| 确认哪些 skill 可用 | 按 Agent 搜索或筛选，验证全局安装和项目私有安装能区分。打开两个项目里的同名条目，核对路径和来源证据。 |
| 分开查看来源与归属 | 打开「GitHub 引入」，在某项的来源详情勾选「我写的」，切换到「我写的」能看到它。缺少机器记录的条目由使用者确认归属。 |
| 按仓库浏览 | 「GitHub 引入」和「我写的」默认列出来源仓库和匹配数量。切换仓库只看该组，超过一页时在组内翻页。搜索与 Agent 筛选更新各组计数。独立的同名本地仓库可以按路径区分，缺少仓库信息的条目进入「未关联仓库」。 |
| 检查发布 | 检查已安装 GitHub 项，在列表和详情核对上次结果。正式发布、同目录内容变化、缺少安装基线应能区分。同仓库其他目录的修改不会触发此项更新。 |
| 阅读与翻译 | 桌面首屏可读原文，窄屏从清单进入并返回原筛选。在正文打开相对路径引用，配置翻译后切换中英文，命令、代码块与文件路径应保留。 |
| 维护指定副本 | 将同一 skill 安装到全局和项目，只升级项目副本。预览后改动本地文件，应提示重新预览。卸载前核对备份路径。解除指向源码的软链后，源文件保持可读。 |
| 收藏与刷新 | 点击星标，重新打开应用、重建索引后「已收藏」仍显示该项。新增文件或项目后重新扫描，列表出现新条目。 |

收藏、归属和手工关联的 GitHub 坐标保存在用户库。安装器的全局、项目 lockfile，与本地 Git 检出、skill 声明提供不同层级的来源证据。检查 GitHub 时，优先使用安装提交或安装目录的 Git tree SHA。目录指纹与项目 lockfile 格式参见 [全局安装记录](https://github.com/vercel-labs/skills/blob/main/src/skill-lock.ts) 和 [项目安装记录](https://github.com/vercel-labs/skills/blob/main/src/local-lock.ts)。

## 提示词库

用户在主导航进入「提示词库」，按用途保存一段原文，之后可以从列表直接复制。每条提示词有正文、标题和一个可选分类。库随本机服务保存，在同一服务的浏览器中共享。

| 场景 | 验收方式 |
| --- | --- |
| 留存一段提示词 | 只粘贴正文并保存，标题取自首行。在已有分类下新建时自动沿用分类，也可以输入新分类。 |
| 找回并复制 | 用正文里的关键词搜索，切换分类后结果随之收窄。通过局域网 IP 打开，点「复制」后粘贴并核对完整正文、换行和缩进。 |
| 继续整理 | 编辑时选择「稍后继续」，在当前标签页重新打开可继续草稿。两台设备同时编辑一条时，后保存的一方可把草稿另存为副本。删除后点击「撤销」可恢复正文和分类。 |

## 初版设计备忘

以下是早期的长期方案和首次扫描记录，保留其模型和决策背景。文中的 Registry、发现、标签、集合与后续里程碑属于历史规划。本轮交付与验收以上表为准。领域词汇见 [GLOSSARY.md](../GLOSSARY.md)。

## 1. 目标与非目标

**目标**：把"只读的 skill 浏览器"变成"可写的 skill 资产台"——能发现本机与远端的 skill、能可靠判断它的来源、能按自己的方式组织它（收藏/标签/集合）、能知道它有没有上游更新或安装问题、能从页面直接登记与安装。

**非目标（v1 明确不做）**：见 §11。

## 2. 概念

五个正交概念与身份键定义见 [GLOSSARY.md](../GLOSSARY.md)；三条不可逆决策见
[ADR-0001](adr/0001-local-first-single-machine.md)（本地优先单机）、
[ADR-0002](adr/0002-five-axes-and-identity-key.md)（五轴模型与身份键）、
[ADR-0003](adr/0003-writable-architecture-and-safety.md)（可写架构与安全默认）、
[ADR-0004](adr/0004-distribution-and-public-repo-boundary.md)（分发与公共仓边界）。

一句话概括模型：**Source 说"从哪来"，Placement 说"在本机哪里"，Collection / Tag / Favorite 说"我怎么看它"**。四者互不派生，任何一个字段都不得同时承担两个职责（现状 `family` 的教训）。

## 3. 信息架构

四个顶级表面 + 两个覆盖层（详情、支持文件查看器）。导航在 URL 中可深链：`#/library`、`#/discover`、`#/tracking/health`、`#/settings`、`#/skill/<identity-key>`。

### 3.1 库 Library（主工作区）

- **左 facet 列**（可多选组合）：收藏 · 集合（v1 一层）· 标签 · 来源（host / repo）· 宿主根 · 健康状态 · 出处可信度 · 是否有可用更新。
- **列表**：多选（框选 / Shift 范围 / 全选筛选结果）；批量动作 = 收藏、加/去标签、入/出集合、认领出处、对适用项执行更新。
- **详情面板**：渲染后的 SKILL.md 正文；**标注块**（可编辑：星标、标签 chips、集合选择器、备注、忽略本次漂移）；**来源块**（host/repo/path + 可信度徽章 + "认领/纠正"入口）；**落点块**（实体路径 + 各宿主根的软链状态）；支持文件列表；动作（复制路径、复制上游链接、在系统文件管理器中打开）。
- **空态**：区分"这台机器没有 skill"（给出宿主根配置入口）与"筛选后为空"（给出一键清空筛选）。

### 3.2 发现 Discover

- **条目列表**：来自默认 Registry + 用户自定义源，每行显示 repo/path、许可证、描述、上次检查时间、状态（未登记 / 已登记 / 已安装 / 已是最新）。
- **动作**：登记（抓取正文缓存到本地，供离线阅读）；安装（先 dry-run 弹窗：将写入的文件清单、许可证、`scripts/` 清单、总体积、目标宿主根 → 确认后执行）；移除登记。
- **源管理**：默认源开关；自定义源（本地文件路径或 URL）增删与刷新。

### 3.3 跟踪 Tracking（三个子视图）

- **安装健康**：问题清单（悬空软链 / 缺失出处 / 本地被手改 / 重复实体），每条带一键修复（重建软链、清掉悬空项、认领出处、合并重复）。
- **上游漂移**：每 skill 一行——本地指纹 vs 上游指纹、判定（可更新 / 本地被手改 / 不可判定）、动作（查看 diff、更新（dry-run）、忽略本次、标记为本地定制）。
- **来源账本**：按 host/repo 聚合的来源分布、待认领项批量认领。这里承载"来源分类管理"，而不是首页。

### 3.4 设置 Settings

宿主根（探测到的列表 + 增删 + 启停）· Registry（默认源开关、自定义源、刷新）· AI 增强（开关、OpenAI 兼容 base/key/model、引擎版本）· 数据（导出/导入用户库、重建索引、清缓存、索引体积）· 关于（版本、本产品 release notes、许可证）。

### 3.5 交互与可达性基线

键盘：`/` 搜索、`j/k` 移动、`Enter` 打开、`Esc` 逐层关闭、`s` 收藏、`t` 加标签；焦点环可见；facets 与列表用 `aria-*` 暴露状态；移动端主从切换保持现有形态但用 URL 驱动。

## 4. 数据与存储

### 4.1 用户库（可 diff、可提交、可导出）

`~/.config/skilldesk/library.json`，单文件、原子替换写（临时文件 + rename）、带 `revision` 递增用于乐观并发。

```jsonc
{
  "version": 1,
  "revision": 42,
  "assets": {
    "src:github.com/mattpocock/skills@skills/engineering/ask-matt": {
      "favorite": true,
      "tags": ["review", "typescript"],
      "collections": ["work/frontend"],
      "note": "",
      "sourceOverride": null,          // 用户纠正的来源；null = 采信推断值
      "ignoreDrift": { "ref": "<sha>", "reason": "本地定制" }
    },
    "loc:9f2c1e7ab3d4e5f6": { "favorite": false, "tags": [] }
  },
  "collections": {
    "work": { "name": "工作", "parent": null, "order": 0 },
    "work/frontend": { "name": "前端", "parent": "work", "order": 1 }
  },
  "registrySources": [
    { "id": "default", "kind": "builtin", "enabled": true },
    { "id": "intranet", "kind": "file", "path": "~/.config/skilldesk/sources/intranet.json" }
  ],
  "settings": { "ai": { "enabled": false, "baseUrl": "", "model": "" } }
}
```

### 4.2 机器索引（可删可重建）

`~/.local/state/skilldesk/index.db`（SQLite，stdlib `sqlite3`）：

| 表 | 主键 | 用途 |
|---|---|---|
| `host_root` | `path` | 探测到的宿主根、启用状态、探测时间 |
| `skill` | `identity_key` | 去重后的 skill 实体：名称、描述、frontmatter、内容指纹、行数/字节 |
| `placement` | `(identity_key, realpath)` | 实体落点与软链关系、链是否悬空 |
| `provenance` | `identity_key` | 推断来源（host/repo/path/ref）、**可信度**、推断依据、检查时间 |
| `snapshot` | `(identity_key, hash, at)` | 内容指纹历史（用于漂移与手改判定） |
| `upstream_check` | `(repo, path)` | 上游最后检查时间、远端 ref、远端 tree 指纹 |
| `health_issue` | `id` | 问题类型、对象、可修复动作 |
| `registry_cache` | `(source_id, host, repo, path)` | 远端条目元数据与正文缓存 |
| `meta` | `k` | schema 版本、最后一次全量扫描时间 |

索引是纯派生物：删掉后 `skilldesk scan` 重建，不丢任何用户数据。

### 4.3 身份键算法

1. **来源归一**：URL → `host`（小写、去 scheme/凭据/`.git`）+ `owner/repo`；仓库内 `path` 用 posix 相对路径指向 `SKILL.md`，去前导 `./`，不做大小写折叠。
2. **键**：有出处 `src:<host>/<repo>@<path>`；无出处 `loc:<sha256(realpath)前16位>`。
3. **提升与降级**：当某个 `loc:` 键被认领为 `src:` 键时，写迁移表并合并标注；反向（上游记录消失）保留 `src:` 键不动，只把可信度降级。
4. **重复合并**：同一 `src:` 键下的多个 placement 合并为一个 skill，多宿主根可见不算重复。
5. 迁移表存 `~/.local/state/skilldesk/migrations.json`，供"迁移向导"回滚。

## 5. HTTP API

只在本机监听；**所有写请求必须带 `X-Skilldesk-Token`**（每次运行随机生成，`skilldesk open` 会把它放进打开的 URL）。响应统一 `{ ok, data }`，错误统一 `{ error: { code, message, details } }`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活 + 索引版本（页面用它做增量刷新，替代现在的整页 reload）；返回前按 mtime 判定是否过期，过期则自动重建（3 秒节流），并用 `rescanned` 告知调用方 |
| GET | `/api/index` | skill 列表，支持 `q, favorite, tag, collection, source, host, health, confidence, limit, offset` |
| GET | `/api/facets` | facet 计数（宿主根类型 / 上游 / 可信度 / 健康问题），附带中文标签 |
| GET | `/api/roots` | 宿主根清单与状态（类型、条目数、是否存在） |
| GET | `/api/issues` | 健康问题清单，可 `kind` / `identity_key` 过滤 |
| GET | `/api/skill/{key}` | 详情：正文 HTML、frontmatter、落点、来源、漂移状态 |
| GET | `/api/skill/{key}/files`、`/api/skill/{key}/file?rel=` | 支持文件列表与内容（大小上限 2 MB，二进制返回元数据） |
| GET | `/api/skill/{key}/asset?rel=` | 图片/二进制资源的原始字节（同样 2 MB 上限与路径约束） |
| GET | `/api/library` | 用户库全文（含 revision） |
| PATCH | `/api/assets/{key}` | 改收藏/标签/集合/备注/来源纠正；带 `If-Match: <revision>`，冲突返回 409 |
| PUT / DELETE | `/api/collections/{id}` | 集合增删改 |
| GET | `/api/registry` | 合并默认源与自定义源的条目 + 本机状态 |
| POST | `/api/registry/refresh` | 刷新远端清单（带缓存 TTL） |
| POST | `/api/import` | 登记；无 `planId` 时只返回计划 |
| POST | `/api/install` | 安装；同上，执行阶段校验 `planId` 与目标未变 |
| POST | `/api/update` | 单 skill 更新（dry-run 优先） |
| POST | `/api/check` | 触发健康 + 漂移检查，可限定 scope |
| POST | `/api/ai/translate` | 可选 AI 增强（默认关，未配置返回 501 而不是报错） |
| GET / POST | `/api/data/export`、`/api/data/import` | 用户库导出/导入（JSON，带 version + revision） |

**dry-run 契约**：`POST /api/import|install|update` 不带 `planId` 时只返回
`{ plan: { planId, target, files:[{path,bytes}], license, scripts:[...], totalBytes, warnings:[] } }`；
带 `planId` 时才写入，并在写入前重算目标指纹，与计划不一致则拒绝（零写入）。计划 5 分钟过期。

## 6. CLI

```
skilldesk open                      # 按需起服务 + 开浏览器，空闲自退
skilldesk serve [--port] [--allow-remote]
skilldesk scan                      # 重建索引
skilldesk list [--json] [facets...]
skilldesk show <key> [--json]
skilldesk health [--json]
skilldesk drift [--json]
skilldesk check [scope]             # 供 cron / CI
skilldesk import <repo[/path]> [--dry]
skilldesk install <repo[/path]> [--dry] [--host <root>] [--force]
skilldesk registry add|remove|list|refresh
skilldesk export <file> / skilldesk import-library <file>
skilldesk doctor                    # 环境、宿主根、锁文件、网关连通性
```

退出码：`0` 正常；`1` 用法/执行错误；**`2` = 检查发现待处理项**（`health`/`drift` 有未处理项），便于 CI 与 cron 直接判定。所有查询命令支持 `--json`，其输出形状就是 API 响应体的子集（两边共用同一序列化层）。

## 7. 安全默认与门禁

1. 默认只绑 `127.0.0.1`；`--allow-remote` 必须同时提供 token，否则拒绝启动。
2. 写请求校验 token + 同源；token 不落盘、不写日志。
3. 所有路径读写经 realpath 校验，限制在声明的宿主根、配置目录、状态目录、缓存目录内；拒绝 `..` 与符号链接逃逸。
4. 静态资源与文件读取修掉现状三处缺陷：`/assets/*` 穿越、`/api/asset` 无上限、`POST /api/build` 无认证（新架构下改为 token 保护的 `/api/check`）。
5. 安装/更新**永不执行** skill 内脚本；dry-run 必须列出 `scripts/` 清单。
6. 许可证门禁：Registry 条目缺许可证 → 标黄并要求显式确认；已知非许可证仓库（如 `dickwu/apple-design-skill`）不进默认源。
7. Markdown 仍在服务端转义并做 URL scheme 白名单（保留现有实现并补测试）。

## 8. 复用 / 重写 / 删除

| 处置 | 对象 | 说明 |
|---|---|---|
| 复用改造 | `markdown.py` 渲染器与清理 | 加测试后原样迁移 |
| 复用改造 | `install.py` 的 sparse-clone / raw 回退策略 | 去掉 `github.com` 硬编码，改为任意 git host |
| 复用改造 | `translate.py` 的分块 + 术语表 + 缓存引擎 | 包成可选 AI provider |
| 重写 | `server.py` → FastAPI 路由 + token + plan 机制 | — |
| 重写 | `scan.py` → 宿主根抽象 + 健康检测 + 身份解析 | 支持项目级多根与嵌套识别 |
| 重写 | `build.py` → SQLite 索引 | 页面不再吃全量 JS payload |
| 重写 | `cli.py`、`web/` 全部 | — |
| 删除 | `commands` 抓取与 `#cmdFilter`（2/133 命中） | 命令信息保留在详情页 |
| 删除 | `catalog/vendor/` 提交物 | 改运行时抓取 + 本地缓存（[ADR-0004](adr/0004-distribution-and-public-repo-boundary.md)） |
| 删除 | `data/skills.js` 全量注入 | 改为分页 API |

## 9. 仓库结构与工具链

```
backend/skilldesk/{config,hosts,identity,scan,library,index,registry,install,drift,health,ai,server,cli}.py
frontend/src/{app,routes,components,api,store}
registry/default.json          # 默认源清单：只有坐标与许可证
docs/{spec.md,adr/}
tests/{backend,frontend,e2e}
pyproject.toml                 # uv 管理
```

后端 `ruff` + `pytest`；前端 `eslint` + `tsc` + `vitest`；`playwright` 三条冒烟（打开库、收藏一个 skill、dry-run 安装）。样式沿用现有 CSS 变量体系，不引 Tailwind 与 UI 组件库。

**非功能目标**：本地首屏 ≤ 300 ms；列表 1000 条虚拟滚动 60 fps；API p95 < 100 ms；索引重建（133 skill）≤ 2 s。

## 10. 里程碑与验收

每个里程碑独立可验收，未达标不进下一个。

**M1 索引与只读库**（2026-11-24 初版自测记录）：宿主根抽象与探测、身份解析、SQLite 索引、健康检测、CLI `scan/list/show/health --json`、只读库视图。
验收：本机 133 个 skill 全部识别且按身份键去重（374 个 placements 收敛为 133 个实体）；`~/.claude/skills` 的 **24 个悬空软链**全部出现在健康清单；lockfile 未覆盖的 **54 个 skill** 全部显式标注（实测 51 个 `待认领` + 3 个由 skill 自身声明、置信度 `declared` 且带证据），任何一个都不得静默当作已记录；`/api/health` 在文件变化后自动重建索引，1 秒内返回。

**M2 用户库与可写 UI**：library.json、收藏/标签/集合 CRUD 与批量操作、facet 筛选、导出导入、迁移向导。
验收：把某个无出处 skill 的目录改名后，标注经内容指纹匹配自动迁移（或给出迁移提示且不静默丢失）；导出再导入后 `revision`、标注、集合层级完全一致；两个标签页并发写同一 asset 时后写者收到 409 而非静默覆盖。

**M3 发现与导入**：默认 Registry + 自定义源、dry-run 契约、登记缓存、安装（任意 git host）、lockfile 写回、许可证与脚本提示。
验收：内网 CODING 源能成功安装（现在做不到）；dry-run 的文件清单与真实写入 diff 为空；缺许可证条目安装前必须出现显式确认；安装后 `skilldesk health` 无新增问题项。

**M4 上游漂移**：`git ls-remote` + 按 skill 子路径 tree 指纹、单 skill 粒度判定、手改检测、更新（dry-run + 写回）、忽略与本地定制标记。
验收：以 `mattpocock/skills`（27 个 skill）为例，上游只改一个 skill 时只有 1 条漂移（现状 Lucy 是 repo 粒度，19 个 repo 报出 89 条噪声）；超过 TTL 才重新检查，未超 TTL 走缓存。

**M5 产品化与发布**：IA 定稿与视觉收尾、README 中英、LICENSE、CI 三平台矩阵、Docker、`0.1.0` 发布、公共仓推送。
验收：在**没有 Lucy、没有 skills CLI** 的干净容器里，`uvx --from skilldesk skilldesk open` 一条命令看到该环境已有的 skill；三平台 CI 全绿；公共仓不含任何第三方 SKILL.md 正文（用脚本核验 `git grep` 无第三方正文）。

## 11. 明确不做（v1）

反向发布到 GitHub · LLM 自动打标签 · 遥测 · 账号/多用户/托管实例 · 后台定时轮询与系统通知 · Windows 的软链与安装承诺（只保证能跑能读能登记）· 嵌套集合的树形 UI（概念允许，UI 一层）· 在线演示实例 · 内网专有适配进公共仓 · 把 skill 内容打进发行包。

## 12. 风险与未决

- **上游配额**：GitHub 匿名 API 60 次/小时、search 10 次/分钟。漂移检查必须走 `git ls-remote`（无配额）+ 缓存 TTL，API 只用于枚举目录。
- **内网源凭据**：安装内网 CODING 源需要用户的 git 凭据；实现上走系统 git 配置，不在产品内保存凭据；CI 用 mock。
- **同名项目**：GitHub 上已有 24 个叫 `skilldesk` 的仓库（无关项目）；PyPI 名保留可用。若将来商标或检索受影响，只需改分发名，身份键与数据格式不受影响。
- **规模**：本机 133 个，但项目级目录里还有数百个（`ai-codereview` 单项目 66 个）。列表必须虚拟滚动 + 服务端分页，不能沿用全量渲染。
- **Windows**：路径与链接语义差异未实测；v1 定位 best-effort，文档需明说。

## 13. M1 落地记录（与设计稿的偏差）

均已实现并验证，记录在此以免后人以为设计稿从未变动：

- **facets 多选推迟到 M2**：`/api/index` 每个轴仍是单值，筛选栏每轴单选；列表多选与批量动作在 M2 与用户库一起做，届时再补多值查询参数。
- **`facets.health` 保留 `dangling_link` 计数**：悬空软链不是 skill 实体，不能作为 skill 过滤器，因此 UI 把它渲染成"跳到跟踪页"的入口而不是筛选行；健康页仍是它们的正式落点。
- **宿主根以 host kind 呈现**：`/api/index` 无 `root` 单值轴，宿主根类型（agents / claude / opencode / project）即筛选轴；单根粒度的筛选等 M2 有用户库后再评估。
- **二进制支持文件返回 `url` 而不是内容**：`/api/skill/{key}/file` 对 image / binary 返回同一 origin 的 `asset` 地址（key 与 rel 均已 percent-encode），脚本类后缀（`.mjs` `.ts` `.sh` 等）按文本展示。
- **词汇口径以 GLOSSARY 为准**：宿主根 = host kinds，来源 = 上游 repo；首版实现稿把两者叫反了（"来源"给了 host kinds），已改正。
- **索引自动重建**：`/api/health` 返回前会按 mtime 判断过期并重建（3 秒节流），`rescanned` 字段告知调用方；因此不需要"刷新数据"这类会写盘的按钮。
