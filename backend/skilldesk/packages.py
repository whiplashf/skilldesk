"""Read a single skill from a pinned Git tree. No checkout filters or repository scripts run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .config import cache_dir
from .markdown import split_frontmatter

MAX_FILES = 400
MAX_BYTES = 8 * 1024 * 1024
SCRIPT_EXTENSIONS = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".ts", ".ps1", ".bat", ".cmd", ".rb"}
NAME = re.compile(r"^[\w.-]+$")


class MaintenanceError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class SkillChoices(MaintenanceError):
    def __init__(self, paths: list[str]):
        super().__init__("请选择要安装的 skill，可用路径有 " + "、".join(paths[:20]), 404)
        self.paths = paths


def relative_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or "\\" in value
        or any(
            not part
            or part in {".", ".."}
            or part.casefold() == ".git"
            or ":" in part
            or any(ord(char) < 32 for char in part)
            for part in parts
        )
    ):
        raise MaintenanceError("仓库内路径无效")
    return value


@dataclass(frozen=True)
class Source:
    host: str
    repo: str
    path: str
    url: str

    @classmethod
    def parse(cls, url: str, path: str = "SKILL.md") -> Source:
        url = url.strip()
        if url.startswith("git@") and ":" in url:
            host, tail = url[4:].split(":", 1)
            url = f"ssh://git@{host}/{tail}"
        elif "://" not in url:
            url = "https://github.com/" + url
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError as error:
            raise MaintenanceError("仓库地址无效") from error
        if (
            parsed.scheme not in {"https", "ssh"}
            or not parsed.hostname
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.username and (parsed.scheme != "ssh" or parsed.username != "git"))
        ):
            raise MaintenanceError("请提供 HTTPS 或 SSH Git 仓库地址")
        host = parsed.hostname.lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host):
            raise MaintenanceError("仓库主机名无效")
        if port and port != (443 if parsed.scheme == "https" else 22):
            host += f":{port}"
        repo = parsed.path.strip("/").removesuffix(".git")
        pieces = repo.split("/")
        if (
            len(pieces) < 2
            or host == "github.com"
            and len(pieces) != 2
            or any(not NAME.fullmatch(piece) or piece in {".", ".."} for piece in pieces)
        ):
            raise MaintenanceError("请填写完整的仓库地址，文档路径单独填写")
        if host == "github.com":
            repo = repo.lower()
        path = relative_path(path.strip())
        if PurePosixPath(path).name != "SKILL.md":
            raise MaintenanceError("仓库内路径必须指向 SKILL.md")
        url = ("ssh://git@" if parsed.scheme == "ssh" else "https://") + host + "/" + repo + ".git"
        return cls(host, repo, path, url)

    def coordinates(self) -> tuple[str, str, str]:
        return self.host, self.repo, self.path

    def json(self) -> dict:
        return asdict(self)


def git(args: list[str], directory: Path | None = None, *, data: bytes | None = None, check: bool = True):
    command = ["git"]
    if proxy := os.environ.get("SKILLDESK_PROXY"):
        command.extend(["-c", f"http.proxy={proxy}"])
    try:
        result = subprocess.run(
            command + args,
            cwd=directory,
            input=data,
            capture_output=True,
            timeout=90,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MaintenanceError("无法运行 Git 或读取仓库超时", 502) from exc
    if check and result.returncode:
        raise MaintenanceError("Git 无法读取该仓库或提交，请核对地址、网络和 Git 访问权限", 502)
    return result


def remote_head(source: Source, ref: str = "") -> str:
    oid = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
    if oid.fullmatch(ref):
        return ref
    if ref and (
        ref.startswith("-") or git(["check-ref-format", "refs/heads/" + ref], check=False).returncode
    ):
        raise MaintenanceError("安装记录中的 Git 引用无效")
    names = ["HEAD"]
    if ref.startswith("refs/"):
        names = [ref]
    elif ref:
        names = ["refs/heads/" + ref, "refs/tags/" + ref]
    patterns = [
        pattern
        for name in names
        for pattern in ([name, name + "^{}"] if name.startswith("refs/tags/") else [name])
    ]
    output = git(["ls-remote", "--", source.url, *patterns]).stdout.decode().splitlines()
    result = {name: sha for sha, name in (line.split("\t", 1) for line in output) if oid.fullmatch(sha)}
    matches = [result.get(name + "^{}", result.get(name, "")) for name in names if name in result]
    if len(matches) != 1:
        raise MaintenanceError("上游分支或标签无法唯一确定，请核对安装记录", 409)
    return matches[0]


def object_store(source: Source, head: str) -> Path:
    slot = cache_dir() / "repositories" / hashlib.sha256(source.url.encode()).hexdigest()
    if not (slot / "HEAD").is_file():
        slot.mkdir(parents=True, exist_ok=True)
        git(["init", "--bare", "--quiet", *(["--object-format=sha256"] if len(head) == 64 else [])], slot)
    if git(["cat-file", "-e", head + "^{commit}"], slot, check=False).returncode:
        git(["config", "remote.origin.url", source.url], slot)
        git(["config", "remote.origin.promisor", "true"], slot)
        git(["config", "remote.origin.partialclonefilter", "blob:none"], slot)
        git(["fetch", "--quiet", "--no-tags", "--depth=1", "--filter=blob:none", "origin", head], slot)
    return slot


def _paths(slot: Path, head: str) -> list[str]:
    output = git(["ls-tree", "-rz", "--name-only", head], slot).stdout
    try:
        return [name.decode() for name in output.split(b"\0") if name and name.split(b"/")[-1] == b"SKILL.md"]
    except UnicodeDecodeError as error:
        raise MaintenanceError("仓库中的文档路径不是 UTF-8 编码") from error


def _license(slot: Path, head: str, source_dir: Path) -> str:
    metadata, _ = split_frontmatter((source_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    if declared := str(metadata.get("license") or "").strip():
        return declared[:200]
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        packaged = source_dir / name
        if packaged.is_file() and packaged.stat().st_size <= 128_000:
            return _license_text(packaged.read_text(encoding="utf-8", errors="replace"), name)
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        size = git(["cat-file", "-s", f"{head}:{name}"], slot, check=False)
        if size.returncode or int(size.stdout) > 128_000:
            continue
        body = git(["cat-file", "blob", f"{head}:{name}"], slot).stdout.decode(errors="replace")
        return _license_text(body, name)
    return ""


def _license_text(body: str, name: str) -> str:
    if match := re.search(r"SPDX-License-Identifier:\s*([^\n\r]+)", body):
        return match[1].strip()[:200]
    for needle, label in (
        ("MIT License", "MIT"),
        ("Apache License", "Apache License"),
        ("GNU GENERAL PUBLIC LICENSE", "GNU GPL"),
    ):
        if needle.casefold() in body.casefold():
            return label
    return "见 " + name if body.strip() else ""


def cli_hash(directory: Path) -> str:
    """The skills CLI v2 content hash, computed only from an already validated package."""
    root = directory.resolve()
    files = []
    total = 0

    def visit(folder: Path, ancestors: set[Path]):
        nonlocal total
        for path in folder.iterdir():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise MaintenanceError("包内软链指向 skill 目录以外")
            if path.name == "metadata.json":
                continue
            if path.is_dir():
                if path.name not in {".git", "__pycache__", "__pypackages__"} and resolved not in ancestors:
                    visit(path, ancestors | {resolved})
                continue
            total += path.stat().st_size
            if len(files) >= MAX_FILES or total > MAX_BYTES:
                raise MaintenanceError("包含软链的文件清单超出单个 skill 的大小限制", 413)
            data = path.read_bytes()
            if b"\0" not in data:
                data = data.replace(b"\r\n", b"\n")
            files.append((path.relative_to(directory).as_posix().encode(), data))

    visit(directory, {root})
    result = hashlib.sha256()
    for name, data in sorted(files):
        result.update(name + b"\0" + str(len(data)).encode() + b"\0" + data)
    return result.hexdigest()


def legacy_cli_hash(directory: Path, files: dict) -> str:
    """v1 project locks use the Node runtime's locale ordering, including for non-ASCII paths."""
    names = [
        p for p, entry in files.items() if entry[0] == "file" and "node_modules" not in Path(p).parts[:-1]
    ]
    if len(names) > 1:
        sort_names = (
            "const paths = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "process.stdout.write(JSON.stringify(paths.sort((a, b) => a.localeCompare(b))));"
        )
        try:
            completed = subprocess.run(
                ["node", "-e", sort_names],
                input=json.dumps(names),
                text=True,
                capture_output=True,
                timeout=8,
                check=True,
            )
            names = json.loads(completed.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return ""
    value = hashlib.sha256()
    for name in names:
        value.update(name.encode())
        value.update((directory / name).read_bytes())
    return value.hexdigest()


def materialize(source: Source, destination: Path, ref: str = "", *, discover: bool = False) -> tuple[Source, str, str]:
    head = remote_head(source, ref)
    slot = object_store(source, head)
    if discover or git(["cat-file", "-e", head + ":" + source.path], slot, check=False).returncode:
        paths = _paths(slot, head)
        if (discover or source.path == "SKILL.md") and len(paths) == 1:
            source = replace(source, path=relative_path(paths[0]))
        elif paths:
            raise SkillChoices(paths)
        else:
            raise MaintenanceError("仓库中没有找到 SKILL.md", 404)
    folder = source.path.rpartition("/")[0]
    tree = head + ":" + folder if folder else head
    listing = git(["ls-tree", "-rlz", tree], slot).stdout
    entries = []
    total = 0
    for line in listing.split(b"\0"):
        if not line:
            continue
        fields, raw_name = line.split(b"\t", 1)
        mode, kind, oid, size = fields.split()
        if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            raise MaintenanceError("此 skill 含需要单独安装的 Git 子模块或特殊文件")
        try:
            name = relative_path(raw_name.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise MaintenanceError("包内文件名不是 UTF-8 编码") from error
        total += int(size)
        entries.append((name, mode, oid, int(size)))
        if total > MAX_BYTES or len(entries) > MAX_FILES:
            raise MaintenanceError(
                f"单个 skill 上限为 {MAX_FILES} 个文件、{MAX_BYTES // (1024 * 1024)} MB", 413
            )
    destination.mkdir()
    data = git(["cat-file", "--batch"], slot, data=b"".join(oid + b"\n" for _, _, oid, _ in entries)).stdout
    offset = 0
    links = []
    for name, mode, oid, size in entries:
        stop = data.index(b"\n", offset)
        if data[offset:stop].split() != [oid, b"blob", str(size).encode()]:
            raise MaintenanceError("Git 返回的文件与预览清单不一致", 409)
        content = data[stop + 1 : stop + 1 + size]
        offset = stop + size + 2
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == b"120000":
            links.append((path, os.fsdecode(content)))
        else:
            path.write_bytes(content)
            path.chmod(0o755 if mode == b"100755" else 0o644)
    for path, target in links:
        if not target or os.path.isabs(target) or "\\" in target or ":" in target:
            raise MaintenanceError("包内软链只能引用该 skill 中的相对路径")
        path.symlink_to(target)
    for path, _ in links:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise MaintenanceError("包内存在无效或循环的软链") from exc
        if not resolved.is_relative_to(destination.resolve()):
            raise MaintenanceError("包内软链指向 skill 目录以外")
    if not (destination / "SKILL.md").is_file():
        raise MaintenanceError("所选目录缺少可读取的 SKILL.md")
    return source, head, _license(slot, head, destination)
