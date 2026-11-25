"""Decide what Skilldesk can change at one specific scanner placement."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from .config import home, load_config
from .hosts import _home_roots
from .identity import lockfile_paths
from .library import read_json
from .packages import MaintenanceError, Source, git


def plain(path: Path) -> bool:
    try:
        return path.is_absolute() and path.resolve() == path
    except (OSError, RuntimeError):
        return False


def stores() -> dict[Path, str]:
    config = load_config()
    disabled = {Path(raw).expanduser().resolve() for raw in config.disabled_roots}
    places = {home() / ".agents/skills": "全局 · Codex / OpenCode"}
    for project in config.projects:
        base = Path(project).expanduser()
        if base.is_dir() and plain(base):
            places.setdefault(base / ".agents/skills", f"项目 · {base.name}")
    return {p: label for p, label in places.items() if plain(p) and p not in disabled}


def link_roots() -> set[Path]:
    config = load_config()
    paths = {path for path, _, _ in _home_roots() if not path.is_relative_to("/etc")}
    for project in config.projects:
        base = Path(project).expanduser()
        paths.update(base / p for p in (".agents/skills", ".claude/skills", ".opencode/skills"))
    disabled = {Path(p).expanduser().resolve() for p in config.disabled_roots}
    return {p for p in paths if plain(p) and p not in disabled}


def lock_path(root: Path) -> Path | None:
    if root not in stores():
        return None
    if root == home() / ".agents/skills":
        paths = lockfile_paths()
        native = (
            Path(os.environ["XDG_STATE_HOME"]).expanduser() / "skills/.skill-lock.json"
            if (os.environ.get("XDG_STATE_HOME") and not os.environ.get("SKILLDESK_LOCKFILE"))
            else paths[0]
        )
        return next((p for p in paths if p.exists() or p.is_symlink()), native)
    return root.parent.parent / "skills-lock.json"


def lock_data(path: Path) -> dict:
    if not plain(path):
        raise MaintenanceError("安装记录的位置已改变，请检查锁文件", 409)
    try:
        data = read_json(path, {"version": 2 if path.name == "skills-lock.json" else 3, "skills": {}})
    except (ValueError, OSError) as exc:
        raise MaintenanceError("无法读取安装记录，请检查锁文件", 409) from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise MaintenanceError("安装记录格式无法识别", 409)
    return data


def source_of(record: dict | None) -> Source:
    if not isinstance(record, dict) or record.get("sourceType") not in {
        "github",
        "git",
        "gitlab",
        "bitbucket",
    }:
        raise MaintenanceError("该目录没有对应的 Git 安装记录", 409)
    path = str(record.get("skillPath") or "")
    if not path:
        raise MaintenanceError("安装记录缺少仓库内的 SKILL.md 路径", 409)
    url = str(record.get("sourceUrl") or record.get("source") or "")
    if not url or (record.get("sourceType") != "github" and "://" not in url and not url.startswith("git@")):
        raise MaintenanceError("安装记录缺少完整的仓库地址", 409)
    return Source.parse(url, path)


def token(path: Path) -> list[int]:
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def manifest(directory: Path) -> dict:
    """Fingerprint all entries, including empty folders, permissions and link text, without following links."""
    entries = {}

    def visit(folder: Path):
        for path in folder.iterdir():
            if path.name.casefold() == ".git":
                raise MaintenanceError("此副本包含 Git 工作区，请在源码仓库中维护", 409)
            mode = path.lstat().st_mode
            rel = path.relative_to(directory).as_posix()
            if stat.S_ISLNK(mode):
                data = os.fsencode(path.readlink())
                entries[rel] = ["link", stat.S_IMODE(mode), len(data), hashlib.sha256(data).hexdigest()]
            elif stat.S_ISDIR(mode):
                if path.is_mount():
                    raise MaintenanceError("目录包含单独挂载的文件系统，请在本机维护", 409)
                entries[rel] = ["dir", stat.S_IMODE(mode), 0, ""]
                visit(path)
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                entries[rel] = ["file", stat.S_IMODE(mode), path.stat().st_size, digest.hexdigest()]
            else:
                raise MaintenanceError("目录包含特殊文件，请在文件系统中维护", 409)

    visit(directory)
    return entries


def tracked(path: Path) -> bool:
    if (path / ".git").exists() or (path / ".git").is_symlink():
        return True
    parent = path.parent
    if any((p / ".git").exists() for p in (parent, *parent.parents)):
        result = git(["--literal-pathspecs", "ls-files", "-z", "--", path.name], parent, check=False)
        return bool(result.returncode or result.stdout)
    return False


def dependencies(item: dict, path: Path) -> list[str]:
    return sorted(
        {p["entry_path"] for p in item["placements"] if p["is_symlink"] and p["realpath"] == str(path)}
    )


def inspect(item: dict, p: dict) -> tuple[list[str], str]:
    path, root = Path(p["entry_path"]), Path(p["host_root"])
    if path.parent != root or not plain(root) or path.name.startswith("."):
        return [], "由宿主或源码仓库维护"
    try:
        if str(path.resolve(strict=True)) != p["realpath"] or bool(p["is_symlink"]) != path.is_symlink():
            return [], "安装位置已变化，请重新扫描"
        if path.is_symlink():
            return (["unlink"], "") if root in link_roots() else ([], "此来源目录由宿主管理")
        lock = lock_path(root)
        if not lock:
            return [], "此目录由宿主或源码仓库维护"
        source = source_of(lock_data(lock)["skills"].get(path.name))
        identity = item["provenance"]
        repo = identity["repo"].lower() if source.host == "github.com" else identity["repo"]
        if source.coordinates() != (identity["host"], repo, identity["path"]):
            return [], "安装记录与此副本的来源不一致，请重新扫描"
        if tracked(path):
            return [], "此目录属于 Git 源码工作区"
        if aliases := dependencies(item, path):
            return ["update"], "卸载前请先解除以下入口的链接：" + "、".join(aliases)
        return ["update", "uninstall"], ""
    except (MaintenanceError, ValueError, OSError, RuntimeError) as exc:
        return [], str(exc) if isinstance(exc, MaintenanceError) else "安装位置无法核实，请重新扫描"


def select(item: dict, entry: str, action: str) -> Path:
    placement = next((p for p in item["placements"] if p["entry_path"] == entry), None)
    if not placement:
        raise MaintenanceError("所选位置不属于此 skill，请重新扫描", 409)
    actions, reason = inspect(item, placement)
    if action not in actions:
        raise MaintenanceError(reason or "此安装位置不支持所选操作", 409)
    return Path(entry)


def install_name(source: Source) -> str:
    parent = Path(source.path).parent
    name = parent.name if parent != Path(".") else source.repo.split("/")[-1]
    if not re.fullmatch(r"[\w-][\w.-]*", name) or name in {"node_modules", "__pycache__"}:
        raise MaintenanceError("仓库目录名不适合作为安装目录名")
    return name
