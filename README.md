# Skilldesk

Skilldesk 是本机的 Agent skill 管理器。打开技能库即可搜索已安装的 skill，查看哪些 Agent 和项目能使用它，阅读正文、收藏，以及检查已安装 GitHub skill 的版本。当前版本待用户验收。

## 启动

需要 Python 3.10+、Node.js 20.19+ 或 22.12+ 和 pnpm。在仓库根目录运行以下命令。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.venv/bin/skilldesk open
```

默认地址为 `http://127.0.0.1:17888`。使用 `skilldesk serve` 可单独启动服务。开发前端时，同时运行后端和 `pnpm --dir frontend dev`。

## 使用技能库

| 在哪里 | 能做什么 |
| --- | --- |
| 本机技能库 | 搜索名称或用途，选择可用 Agent，组合「GitHub 引入」「我写的」「已收藏」与来源、健康等筛选。点击列表或正文旁的星标即可收藏。 |
| 来源仓库 | 「GitHub 引入」和「我写的」默认按仓库浏览。点击仓库名查看该组的 skill，旁边的数量随搜索和 Agent 筛选更新。各个范围都可以切换到「平铺列表」。 |
| 正文 | 桌面并排显示列表和正文，窄屏点击一项进入阅读。正文里的本地引用可以继续打开和返回。支持文件和来源详情默认折叠。 |
| 来源与可用范围 | 查看安装位置、项目范围与来源证据，勾选「我写的」，或补全 GitHub 仓库和仓库内的 `SKILL.md` 路径。缺少来源的条目保留在「全部」中，作者由使用者确认。 |
| GitHub 版本 | 在详情中检查一项，或在「GitHub 引入」检查当前页。显示正式发布、目录内容变化、已是最新或证据不足。比较按 skill 目录进行，结果缓存一小时，详情可重新检查。私有仓库可配置 `SKILLDESK_GITHUB_TOKEN`。 |
| AI 翻译 | 在设置填写兼容 Chat Completions 的服务地址、模型和可选密钥，然后在正文点击「AI 翻译成中文」。可随时切回原文，代码和引用保留，译文按内容、服务与模型缓存在本机。 |
| 设置与安装健康 | 添加或移出要扫描的项目，查看扫描根、索引和问题清单。列表右上角的重新扫描按钮会重新读取本机文件。 |

浏览库、筛选、收藏和原文阅读均可离线使用。点击翻译会将这篇正文的可翻译文字发给所选服务。点击版本检查会访问已安装项对应的 GitHub 仓库。

仓库分组优先采用你在详情中关联的 GitHub 仓库。自写 skill 可以从本地 Git 工作目录识别来源，同名的独立本地仓库用路径区分。缺少仓库信息的条目集中在「未关联仓库」。

给缺少来源记录的 skill 勾选「我写的」或补全 GitHub 坐标后，安装健康中的待认领数量随即更新。版本检查优先使用已安装的提交或目录指纹。缺少安装证据时会标记为「已建立基线」，后续可判断上游是否变化。设置里的「查询 GitHub 额度」由你手动触发。

## 扫描范围与数据

默认扫描用户级的 Codex、Claude Code、OpenCode 和共享 `.agents/skills`，包括 Codex 的 `.system` 子目录。对于在 Codex 配置里明确启用、且能唯一确定安装版本的插件，也会读取其清单中声明的 skill 目录。设置中添加的项目会扫描其 `.agents/skills`、`.claude/skills` 和 `.opencode/skills`。Agent 范围表示对应客户端可读取的安装位置。私有插件目录或其他客户端可通过 `extraRoots` 指定目录和 Agent。

配置保存在 `~/.config/skilldesk/config.json`。例如，在默认范围外添加一个客户端的技能目录可以写成这样。

```json
{
  "extraRoots": [
    { "path": "/absolute/path/to/skills", "label": "My Agent", "agents": ["my-agent"] }
  ]
}
```

| 数据 | 默认位置 |
| --- | --- |
| 项目目录、个人收藏与归属、翻译设置 | `~/.config/skilldesk/` 下的 `config.json`、`library.json`、`ai.json` |
| 本机扫描索引 | `~/.local/state/skilldesk/index.db` |
| 译文与上游检查结果 | `~/.cache/skilldesk/` |

目录遵循 XDG，也可分别用 `SKILLDESK_CONFIG_DIR`、`SKILLDESK_STATE_DIR`、`SKILLDESK_CACHE_DIR` 指定。环境配置支持 `SKILLDESK_PROJECTS`（路径列表），以及 `SKILLDESK_AI_BASE_URL`、`SKILLDESK_AI_MODEL` 和与服务地址配套的 `SKILLDESK_AI_API_KEY`。已有收藏与归属独立于扫描索引保存。

## 命令行

| 命令 | 作用 |
| --- | --- |
| `skilldesk scan` | 重建本机索引 |
| `skilldesk list` / `skilldesk show <identity-key>` | 筛选安装清单或查看一个 skill |
| `skilldesk health` | 列出安装问题，有待处理项时退出码为 2 |
| `skilldesk doctor` | 检查目录、lockfile 和索引 |

查询命令支持 `--json`。运行后端测试可安装 `pip install -e '.[dev]'` 后执行 `python -m pytest`。当前验收范围见 [设计规格](docs/spec.md)，数据概念见 [术语表](GLOSSARY.md)。

## 许可

MIT。
