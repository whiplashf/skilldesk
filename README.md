# skilldesk

**Local-first manager for agent skills.** One command indexes every `SKILL.md` on your
machine, says where each one really came from, shows which copies are broken — then gives
you a web UI to browse and (from M2 on) organize them.

> **Status: M1 (0.1.0)** — index, provenance grading, install health and a read-only
> library UI. Favorites, tags, collections, GitHub import/install and upstream-drift
> tracking are the next milestones.

## 为什么需要它

本机 skill 的真实状态很难说清。一台开发机的实测：装了 **133** 个 skill，其中 **79** 个能追到具体上游仓库、
**3** 个只有 skill 自己的声明、**51** 个完全无出处；另有 **24** 个软链指向已经被删掉的目录，而界面照样显示"正常"。

问题的根子是：来源、落点、组织方式、跟踪状态被挤进同一个字段。skilldesk 把它们拆成互相正交的四件事：

| 概念 | 回答的问题 |
|---|---|
| **Source（来源）** | 从哪个 host / 仓库 / 哪条路径来的，以及**这个判断有多可信** |
| **Placement（落点）** | 在本机哪里：实体目录 + 哪些 agent 目录通过软链到达它 |
| **Collection / Tag / Favorite** | 我按什么方式组织它（M2） |
| **Drift / Health（跟踪）** | 上游有没有新内容、本机副本有没有问题 |

一个字段不再同时承担两个职责。完整定义见 [GLOSSARY.md](GLOSSARY.md)。

## M1 能做什么

- **扫全宿主根**：`~/.agents/skills`、`~/.claude/skills`、`~/.codex/skills`、`~/.config/opencode/skills`、
  项目内 `.agents|.claude|.opencode/skills`（可配置，支持禁用与追加自定义根）
- **按 realpath 去重**：同一实体经多个宿主根可见只算一个 skill，记录为多个"落点"（实体 / 软链）
- **来源分级，绝不猜**：lockfile 记录（`recorded`）> skill 自身声明（`declared`，含证据）> **待认领**（`none`）
- **安装健康**：悬空软链、缺失来源、重复实体三条检测，`health` 有未处理项时退出码 `2`
- **只读 Web UI**：库（facets 筛选 + 分页 + 详情）、跟踪（健康问题）、设置（宿主根与索引）；深浅色、键盘 `/ ↑ ↓ Enter Esc`
- **CLI 全部支持 `--json`**，输出形状是 API 响应的子集，脚本和页面不会各说各话
- `/api/health` 按 mtime 判定索引是否过期并自动重建（3 秒节流），页面无需手动刷新

## 快速开始

```bash
git clone https://github.com/whiplashf/skilldesk.git && cd skilldesk
uv venv .venv && uv pip install --python .venv/bin/python -e '.[dev]'

.venv/bin/skilldesk scan       # 建索引
.venv/bin/skilldesk health     # 安装健康；有未处理项退出码 2
.venv/bin/skilldesk list       # 列表（--json 给脚本用）

# 前端（可选：API 可以单独用）
cd frontend && pnpm install && pnpm build && cd ..
.venv/bin/skilldesk open --port 17888
```

要求：Python 3.10+；前端需要 Node 20+ 与 pnpm。

| 命令 | 作用 |
|---|---|
| `skilldesk scan` | 重建索引 |
| `skilldesk list [--q --host --source --confidence --health --json]` | 列 skill |
| `skilldesk show <identity-key> [--json --html]` | 单个 skill 详情 |
| `skilldesk health [--json]` | 安装健康，退出码 2 = 有待处理项 |
| `skilldesk doctor [--json]` | 环境、宿主根、lockfile、索引自检 |
| `skilldesk serve` / `open` | 起 HTTP 服务 / 起服务并打开浏览器 |

## 身份键

收藏、标签这些用户标注要能跨重装、改名、多宿主可见保持稳定，所以标注绑定在**身份键**上：

- 有出处：`src:<host>/<repo>@<path-to-SKILL.md>`（repo 路径可含任意层级的 group）
- 无出处：`loc:<sha256(realpath)>`（落点指纹）

**不用**目录名，也**不用** frontmatter 里的 `name`——它们会重名、会改名，用户标注会跟着丢。

## 数据放哪

| 用途 | 路径（XDG，可用 `SKILLDESK_*_DIR` 覆盖） |
|---|---|
| 配置 / 用户库（M2 起） | `~/.config/skilldesk` |
| 机器索引（可删可重建） | `~/.local/state/skilldesk/index.db` |
| 缓存 | `~/.cache/skilldesk` |

服务默认只绑 `127.0.0.1`。

## 设计文档

- [docs/spec.md](docs/spec.md) — 信息架构、数据模型、API/CLI 契约、安全默认、里程碑与验收标准
- [docs/adr/](docs/adr/) — 四条不可逆决策：本地优先单机 / 五轴模型与身份键 / 可写架构与安全默认 / 分发与公共仓边界
- [GLOSSARY.md](GLOSSARY.md) — 领域词汇（含"不要用的同义词"）

## 路线图

| 里程碑 | 内容 |
|---|---|
| **M1 ✅** | 索引、来源分级、安装健康、只读库 |
| M2 | 用户库：收藏、标签、集合、批量操作、迁移向导 |
| M3 | 发现与导入：Registry、dry-run 安装（任意 git host）、lockfile 写回 |
| M4 | 上游漂移：单 skill 粒度判定、可更新/被手改、更新动作 |
| M5 | 产品化：pipx/uvx 分发、Docker、CI、中英文档、0.1.0 发布 |

## 许可

MIT。第三方 skill 的正文不在本仓：Registry 只存坐标与许可证，skill 内容一律运行时抓取并缓存在本地。
