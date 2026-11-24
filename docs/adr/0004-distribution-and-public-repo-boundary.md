# MIT 许可、uvx/pipx 分发，公共仓不提交第三方 skill 正文

以 MIT 发布（与 `npx skills` 及多数 skill 仓一致，社区摩擦最低）。主分发是 `uvx`（试跑）与 `pipx`（常装），`docker run` 兜底，不做 brew 公式（维护成本大于收益）；演示用 README 静态截图 + 可选 Pages 只读 demo，不维护在线实例。公共仓为 `github.com/whiplashf/skilldesk`，PyPI 名 `skilldesk`（2026-11-24 核实两处均未占用）；仓库级 git 身份使用 `whiplashf` + GitHub noreply 邮箱，避免把公司邮箱写进公开提交历史。

**约束**：现在 `catalog/vendor/` 把第三方仓库的 `SKILL.md` 全文提交进仓，公开即构成再分发。公共仓只允许放 Registry 坐标（host/repo/path、许可证、描述），skill 正文一律运行时抓取并缓存在本地且 gitignore。

## 后果

- 公开仓历史从零开始；内网 CODING 仓保留完整历史，作为私有镜像不推公共。
- 任何"把 skill 内容打进包/打进仓"的便利做法（离线包、预置快照）都被这条约束否决，只能走运行时缓存。
- 缺少许可证的 Registry 条目在安装前必须显式提示，不得静默安装。
