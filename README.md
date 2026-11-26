# Skilldesk

想直接复制提示词？打开[按分类整理的提示词库](prompts/README.md)，每条都是独立的纯文本文件。

Skilldesk 是本机的 Agent skill 和提示词管理器。打开技能库即可搜索已安装的 skill，查看哪些 Agent 和项目能使用它，阅读正文、收藏，以及检查已安装 GitHub skill 的版本。提示词库可以按用途保存和查找原文，一键复制到正在使用的工具。当前版本待用户验收。

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

局域网内免登录访问可运行 `skilldesk serve --host 192.168.1.10 --allow-lan`，将示例 IP 换成本机的局域网地址。同一局域网中能访问该地址的设备可以直接打开页面、管理这台机器的 skill。

## 使用提示词库

在主导航打开「提示词库」，点「新建提示词」粘贴正文即可保存。标题留空时取正文首行，分类可以选已有名称，也可以直接输入新名称。通过分类或标题、正文关键词找到条目后，点「复制」即可取用完整原文，换行与缩进一并保留。

点标题可以展开阅读、编辑或更换分类。编辑时选「稍后继续」会把草稿留在当前浏览器标签页。确认删除后可点「撤销」。通过局域网访问时，所有设备看到同一份仓库文件。

「保存」直接写入当前 Skilldesk 仓库的 [prompts/](prompts/README.md)。正文按分类存为独立的纯文本文件，改名、移动分类、删除和撤销都会更新相应文件与索引。这些修改随项目平时的 Git 提交和推送一起到 GitHub。

升级后第一次打开提示词库会自动补入旧库中的条目。两边内容有差异时，旧库版本以带「（旧库）」的标题保留。原来的配置文件保留作备份。

## 使用技能库

| 在哪里 | 能做什么 |
| --- | --- |
| 本机技能库 | 搜索名称或用途，选择可用 Agent，组合「GitHub 引入」「我写的」「已收藏」与来源、健康等筛选。点星标收藏，取消后可点「撤销」。搜索框内按 Esc 清除搜索词。 |
| 功能分类 | 按「页面设计」「代码开发」「代码评审」等主要用途浏览，可同时按来源分组、按 Agent 筛选。点击「AI 分类」分批整理全库待分类项，支持暂停和继续。详情里可以调整分类，也可以恢复「跟随 AI 分类」。 |
| 按来源分组 | 开启结果标题旁的「按来源分组」，同一份列表会显示各仓库、提供方和本地来源。点击来源名可单独展开或收起，关闭开关即按名称查看。只有一个来源时直接显示技能。 |
| 正文 | 桌面并排显示列表和正文，窄屏点击一项进入阅读。正文里的本地引用可以继续打开和返回。支持文件和来源详情默认折叠。 |
| 来源与可用范围 | 详情顶部可以打开 GitHub 仓库，有文档路径时还能直接打开对应的 `SKILL.md`。展开后可查看安装位置和来源依据，或编辑跟踪的仓库。没有上游来源的本地技能可以勾选「我写的」。 |
| GitHub 版本 | 在详情中检查一项，或在「GitHub 引入」检查当前页。每次手动检查都会读取最新的上游信息，同一批次的同仓库条目共用一次读取。详情显示该 skill 的正式发布或目录变化，以及上次成功核验的时间。私有仓库可配置 `SKILLDESK_GITHUB_TOKEN`。 |
| AI 翻译 | 首次在正文点「设置中文翻译」，填写兼容 Chat Completions 的服务地址、模型和可选密钥，选「保存并翻译这篇」。可随时切回原文。命令、代码块和引用保留，译文按内容、服务与模型缓存在本机。 |
| 维护安装 | 在详情的「来源与可用范围」展开安装位置。可以预览升级、卸载受管理的副本，或单独解除选中 Agent 的软链。 |
| 设置与安装健康 | 在设置中管理项目目录。在安装健康点「刷新」可重新扫描，直接确认未知来源，或预览、解除已核实的失效链接。 |

浏览库、筛选、收藏和原文阅读均可离线使用。外链图片在点「加载外部图片」后才会访问图片站点。点击翻译会将这篇正文的可翻译文字发给所选服务。点击版本检查会访问已安装项对应的 GitHub 仓库。

仓库分组优先采用你在详情中关联的 GitHub 仓库。自写 skill 可以从本地 Git 工作目录识别来源，同名的独立本地仓库用路径区分。通过文档站、Codex 内置目录或已启用插件分发的 skill 也可以按提供方查看。其余条目集中在「未关联仓库」。

给缺少来源记录的 skill 勾选「我写的」或补全 GitHub 坐标后，安装健康中的待认领数量随即更新。版本检查优先使用已安装的提交或目录指纹。缺少安装证据时会标记为「已建立基线」，后续可判断上游是否变化。设置里的「查询 GitHub 额度」由你手动触发。

### 从仓库安装与维护

在设置页顶部粘贴 GitHub 仓库、分支、目录或 `SKILL.md` 文件链接，点击「查找技能」。也支持 `owner/repo` 和完整 HTTPS、SSH Git 地址。只有一个技能时直接进入预览，有多个时从列表选择。目录链接限定查找范围，文件链接直接预览指定技能。默认安装到全局，已添加的项目也可以作为安装位置。确认后才会写入所选范围的 `.agents/skills` 和安装记录。安装需要本机 Git 和仓库读取权限，打开设置和浏览技能库均可离线。

预览会展示安装位置、提交、文件增删改、随包脚本和许可证。升级沿用该副本安装记录中的仓库、分支或标签，确认时使用预览的提交。跟踪仓库有别于安装来源时，详情会列出两者。文件和记录一致时直接显示「已是最新」。只有安装记录需要变更时可以单独更新记录。预览有效期为十分钟，本地文件或安装记录发生变化后需要重新预览。替换或卸载的原副本保存在 `$XDG_STATE_HOME/skilldesk/backups/`（默认 `~/.local/state/skilldesk/backups/`），完成后可以复制备份路径取回文件。

源码工作区、宿主插件及缺少可信安装记录的实体目录可以阅读。Agent 的软链支持单独解除。卸载被其他已知入口引用的实体前，先在这些入口解除链接。项目锁保留原有格式。旧版 v1 的多文件校验使用本机 Node.js 的排序规则。如果机器缺少 Node.js，旧 CLI 可在下次同步时重建校验值，Skilldesk 自己仍会记录完整文件指纹。

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
| 提示词正文、分类和目录 | 当前代码仓库的 `prompts/` |
| AI 功能分类 | `~/.config/skilldesk/skill-categories.json`，按 skill 名称和内容指纹保存。手动选择保存在用户库中。 |
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

桌面与手机交互回归使用临时技能库。先构建前端，安装 `pip install -e '.[browser]'` 和 `python -m playwright install chromium`，再运行 `python -m pytest tests/browser`。

## 许可

MIT。
