# Lucy 的技能模型能给本项目什么

> 状态：调研完成，未采纳（2026-11-25）。这是一份决策输入，不改变当前行为。

Lucy 是这台机器上更早的技能看板：每天检查上游、把简报推到飞书。本项目不做推送，但在「自写技能」和「已确认」这两件事上，它的建模比当前实现细一档。下面只记值得搬的部分、搬之前要先补的差距，以及明确不搬的部分。

## 1. Lucy 的机制

三块配置（`lucy.toml`）与本项目相关：

| 配置 | 含义 |
| --- | --- |
| `[[skills.local]]` | 项目仓库是源，`~/.agents/skills/<name>` 是已装副本；`path` / `label` / `roots` 三项，roots 默认 `.opencode/skills`、`.claude/skills`、`.agents/skills`，同名按顺序取第一个 |
| `[skills.map]` | 没有来源字段的技能在这里补 `名称 = owner/repo` |
| 顶层安装记录清单 | 不只读 skills CLI 的锁，其他安装器的记录也可以列进来 |

状态表分两张：`local_skill_repos`（仓库、label、roots、HEAD）与 `local_skills`（源 hash、已装 hash、差异数、最近提交、是否脏、提醒基线）。`check` 只读，`skills local sync` / `skills update` 才写 store，写前整份备份。列表里这些条目显示「（项目）<label>」。

## 2. 逐条对照

### 2.1 项目源应该是一类上游，而不是「没有上游」

Lucy 的说法是：自写技能的上游就是项目仓库，可校验（路径 + hash）；store 里那份只是副本，「落后」表现为「源待同步」，而不是「无上游」。

本项目（`backend/skilldesk/hosts.py`）：项目被加进 `config.projects` 时会扫它的 `.agents/skills`、`.claude/skills`、`.opencode/skills`——目录约定和 Lucy 一致——但每一份都是独立实体：

- 项目副本和 store 副本各拿一个 `loc:` 键，内容一致反而触发「重复实体」；
- 没有「源 / 副本」方向，也没有「待同步」状态；
- 自写技能在扫描看来仍是 `none`，只能靠人点「我写的」。

建议：配置里加 `localRepos`（path / label / roots），扫描后按名字匹配 store 实体，记下源路径、源目录 tree hash、是否有未提交改动，并把它当作已认领（证据 = 项目路径）。健康页的「重复实体」在这类配对上应降级为提示。

改动量：中（配置 + 扫描关系 + 认领 + 详情展示）。收益：本机 43 个待认领里有 3 个会立刻归位，以后新增项目自动生效。

### 2.2 认领应该是一份名单

Lucy 用 `[skills.map]` 一张表解决「手拷进来的技能不知道来自哪」，再加上可配置的多份安装记录。

本项目（`backend/skilldesk/identity.py`）：安装记录是代码里的固定候选（外加一个环境变量逃生口）；认领只有详情页逐条操作。

建议：`~/.config/skilldesk/sources.toml`，至少两块：`[[records]] path = …`（额外安装记录）与 `[map] 名称 = "owner/repo"`。优先级建议：安装记录 > 技能自述 > 项目源 > 名单 > 逐条认领。

改动量：小。收益：43 次点击变成一份可 diff、可带到新机器的清单。

### 2.3 记录缺仓库内路径时，去仓库里找

Lucy 在镜像里按 frontmatter 的 name 找子目录（`find_subpath`）。

本项目：索引里有 3 个「已声明」全部是「知道仓、不知道路径」，身份键退回 `loc:`，版本检查直接不可用。`backend/skilldesk/installer.py` 里已有候选发现（`candidates()`、`_tar_candidates()`）。

建议：详情页加「补全路径」动作，复用候选发现，把结果写回认领的 path；这样「已声明」也能查版本。

改动量：小到中。

### 2.4 重复实体可以机械修

Lucy 的 `tidy`：把散在各 agent 目录里的实体收进 store，原地换成软链。

本项目：`backend/skilldesk/repair.py` 明确拒绝重复实体，人只能自己决定删哪份；现有修复只覆盖悬空软链。

建议：内容 hash 相同才允许修；沿用现有安全边界（只动已登记宿主根里的条目、先备份、失败不碰原物）。

改动量：中。

### 2.5 确认要绑定到那一次变更

Lucy 的 `local_skills.notified_hash`：同一差异只提醒一次，上游再变会重新提醒。

本项目：版本检查每次都报同一条变化，spec 里计划的「忽略本次漂移」尚未实现。

建议：基线里记 `acknowledgedTree`，检查时上游 tree 与之相等就报「已确认」；上游一变自动恢复。

改动量：小。

## 3. 不搬的部分

- **仓库粒度的漂移判定**。spec 的验收条款已经要求按技能目录指纹判断；Lucy 的仓库粒度在一个多技能仓上会一次报出十几条噪声，别退回去。
- **生成升级脚本给人跑**。本项目的两阶段 plan / apply（diff、校验上游未移动、备份保留 3 份）更安全。
- **日报推送与来源镜像**。那是 Lucy 的产品形态（每天一次、为大规模仓库做离线 diff）。本项目上百个技能走 GitHub API 够用；真要摘要，应做成独立的 `skilldesk digest` 命令交给定时任务，而不是塞进检查路径。

## 4. 如果采纳，建议的顺序

1. 只读版：项目源 / 待同步 / 源有未提交改动，只显示，不写文件。验收：本机那 3 个技能显示为项目源，且不再出现在「待认领」。
2. 配置文件：`sources.toml` 的 `[[records]]` 与 `[map]`。验收：名单里的一条把对应技能标为已认领，删掉后恢复。
3. 路径补全。验收：一个「已声明无路径」的技能能查出上游版本。
4. 重复实体修复。验收：内容相同的两份收敛成「实体 + 软链」，hash 不同时拒绝。
5. 漂移确认。验收：确认后不再重复提示，上游再变重新提示。

## 5. 证据（2026-11-25）

- 索引统计：`recorded` 93、`declared` 3、`none` 43；3 个 `declared` 的 `path` 全为空。
- Lucy 本机实测：`lucy skills local` → 1 个仓库、3 个技能、全部 aligned；`lucy skills` 中它们显示「（项目）<label>」。
- 代码位置：本项目 `backend/skilldesk/{identity,hosts,installer,repair}.py`；Lucy 仓的 `src/lucy/{config,localskills,skills,state,cli}.py` 与 `config/lucy.toml`。
