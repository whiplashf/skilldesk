# skill 资产管理 · 领域词汇

本文件只定义概念，不记录实现方式（存储格式、技术栈、接口形状等属于 ADR 与 spec）。定义暂用中文，公开发布版再补英译。

## 对象

**Skill**：
一个 agent 能力单元——以 `SKILL.md` 为入口的目录，可附带 `references/`、`scripts/`、`assets/` 等支持文件。
_Avoid_：技能包、插件、tool、prompt

**Host Root（宿主根）**：
某个 agent 客户端约定的 skill 目录（Claude Code、Agents、OpenCode、项目内 `.claude/skills` 等）。它是本工具的扫描边界，也是安装边界。
_Avoid_：安装目录、root、agent 目录

**Placement（落点）**：
一个 skill 在本机的实体形态：实体目录在哪，以及哪些宿主根通过软链到达它。同一实体经多个宿主根可见，仍是一个 skill。
_Avoid_：安装位置、路径、副本

## 身份

**Identity Key（身份键）**：
一个 skill 在重装、改名、多宿主可见之后仍然稳定的身份，用户的标注（收藏、标签、集合、来源纠正）都绑定在它上面。有出处时取上游身份，无出处时取落点指纹；绝不取目录名或 frontmatter 里的名字。
_Avoid_：id、slug、hash、路径

## 组织轴（互相正交，不得混用）

**Source（来源）**：
一个 skill 的上游身份——哪个 host、哪个仓库、仓库内哪条路径、哪个内容指纹，以及这个判断的可信度。它描述"从哪来"，不描述"怎么组织"。
_Avoid_：出处、上游、provenance、family、仓库分组

**Source Confidence（来源可信度）**：
对 Source 判断的确定程度，从"机器记录"到"纯名字推测"。可信度不足时必须显示为待认领，而不是当作事实。
_Avoid_：置信度、猜测

**Collection（集合）**：
用户自建的分组，可嵌套，一个 skill 可属多个。用于"我的前端工具"这类长期组织，可导出共享。
_Avoid_：分类、目录、group、族

**Tag（标签）**：
用户随手贴的扁平自由词，多值、不成层、不承担分类职责，只用于交叉筛选。
_Avoid_：分类、category、集合

**Favorite（收藏）**：
用户对单个 skill 的独立星标，是布尔关系，不是标签的一个取值。
_Avoid_：星标标签、重要标签

**User Library（用户库）**：
用户自己的认知与组织——收藏、标签、集合、来源纠正——的总体。它与 skill 内容文件分离，可导出、可再导入。
_Avoid_：数据库、配置、缓存

## 发现

**Local Discovery（本机发现）**：
扫描宿主根得到本机已有 skill 的过程，含重复实体的合并、悬空软链的识别、嵌套 skill 的识别。
_Avoid_：扫描、sync

**Remote Discovery（远端发现）**：
在本机之外寻找尚未安装的 skill 的过程。只通过 Registry 进行，不做全网爬取。
_Avoid_：市场、marketplace、搜索

**Registry（源清单）**：
可插拔的"已知远端 skill"清单（本地文件或在线源），记录上游坐标与许可证。远端发现与登记都以它为唯一入口。
_Avoid_：市场、索引、sources

**Default Registry（默认源清单）**：
随产品发布的 Registry 初始内容，只含上游坐标与许可证，不含任何 skill 正文；用户可关闭、可增补自己的源。
_Avoid_：内置市场、预置源、sources.json

**Import（登记）**：
把一个远端 skill 记入 Registry 并留下可离线阅读的副本，不改变任何宿主根、不改变 agent 行为。
_Avoid_：安装、添加、收藏

**Install（安装）**：
把一个 skill 实体化进某个宿主根，登记出处并建立软链。这是唯一改变 agent 行为的动作，必须显式确认。
_Avoid_：导入、拉取、部署

## 变更与健康

**Upstream Drift（上游漂移）**：
上游某个 skill 的内容相对本机副本发生变化。以单个 skill 为粒度判断，不是整个仓库。
_Avoid_：更新提醒、版本落后、repo 更新

**Install Health（安装健康）**：
本机副本的结构性问题——悬空软链、缺失出处、本地被手改、同一 skill 多处重复。
_Avoid_：状态、lint、检查

**Tracking（跟踪）**：
对 Install Health 与 Upstream Drift 的持续观测与呈现。二者是两件事，不合称"自动跟踪"。
_Avoid_：自动跟踪、监控、同步
