"""Command line interface.

Design rule: every query command supports ``--json`` and its payload is a subset
of the HTTP API payload, so scripts and the web UI never disagree.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__, library
from . import index as index_mod
from .config import config_dir, index_path, load_config, state_dir
from .health import KINDS as HEALTH_KINDS
from .health import detect
from .identity import CONFIDENCE_LABEL, lockfile_paths
from .scan import scan

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_FINDINGS = 2


def _dump(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(lines)


def _claims(conn) -> set[str]:
    """User claims: the annotations that answer findings the scan left open."""
    return set(library.claims(library.resolved(library.stored(), conn)["assets"]))


def _ensure_index() -> None:
    if not index_mod.is_current(index_path()):
        result = scan(load_config())
        index_mod.rebuild(result, detect(result.skills, result.dangling), index_path())


def _build_index() -> dict[str, Any]:
    result = scan(load_config())
    issues = detect(result.skills, result.dangling)
    meta = index_mod.rebuild(result, issues, index_path())
    placements = sum(len(skill.placements) for skill in result.skills)
    unclaimed = sum(1 for skill in result.skills if skill.provenance.confidence == "none")
    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1
    return {
        **meta,
        "skills": len(result.skills),
        "placements": placements,
        "dangling": len(result.dangling),
        "unclaimed": unclaimed,
        "issues_by_kind": by_kind,
        "roots": [
            {"path": str(root.path), "kind": root.kind, "exists": root.exists} for root in result.roots
        ],
        "index": str(index_path()),
    }


def cmd_scan(args: argparse.Namespace) -> int:
    summary = _build_index()
    if args.json:
        _dump(summary)
        return EXIT_OK
    roots = summary["roots"]
    existing = sum(1 for root in roots if root["exists"])
    print(f"扫描完成 · {len(roots)} 个宿主根（{existing} 个存在）")
    print(f"  skills      {summary['skills']}")
    print(f"  placements  {summary['placements']}")
    print(f"  dangling    {summary['dangling']}")
    print(f"  unclaimed   {summary['unclaimed']}")
    print(f"  issues      {summary['issues']}")
    for kind, count in sorted(summary["issues_by_kind"].items()):
        label = HEALTH_KINDS.get(kind, {}).get("label", kind)
        print(f"    {kind:<18} {count:>4}  {label}")
    print(f"索引: {summary['index']}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    _ensure_index()
    conn = index_mod.connect(index_path())
    try:
        assets = library.resolved(library.stored(), conn)["assets"]
        payload = index_mod.list_skills(
            conn,
            q=args.q,
            host=args.host,
            source=args.source,
            confidence=args.confidence,
            health=args.health,
            assets=assets,
            limit=args.limit,
            offset=args.offset,
        )
        for item in payload["items"]:
            library.apply_claim(item, library.claim_of(assets.get(item["identity_key"], {})))
    finally:
        conn.close()
    if args.json:
        _dump(payload)
        return EXIT_OK
    rows = []
    for item in payload["items"]:
        provenance = item["provenance"]
        source = provenance["label"] or "—"
        confidence = CONFIDENCE_LABEL.get(provenance["confidence"], provenance["confidence"])
        rows.append(
            [
                item["name"][:32],
                source[:44],
                confidence,
                ",".join(item["host_kinds"]),
                ",".join(item["health"]) or "ok",
            ]
        )
    print(_table(["NAME", "SOURCE", "CONFIDENCE", "ROOTS", "HEALTH"], rows))
    print(f"\n{payload['total']} 个 skill（显示 {len(payload['items'])}，offset {payload['offset']}）")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    _ensure_index()
    conn = index_mod.connect(index_path())
    try:
        if args.html:
            from .markdown import render, split_frontmatter
            from .scan import read_body

            skill = index_mod.get_skill(conn, args.key)
            if skill is None:
                print(f"找不到 skill: {args.key}", file=sys.stderr)
                return EXIT_ERROR
            body = read_body(skill["realpath"])
            if body is None:
                print("SKILL.md 已从磁盘消失", file=sys.stderr)
                return EXIT_ERROR
            _frontmatter, markdown_body = split_frontmatter(body)
            print(render(markdown_body))
            return EXIT_OK
        skill = index_mod.get_skill(conn, args.key)
        annotations = library.resolved(library.stored(), conn) if skill else {"assets": {}}
    finally:
        conn.close()
    if skill is None:
        print(f"找不到 skill: {args.key}", file=sys.stderr)
        return EXIT_ERROR
    library.apply_claim(skill, library.claim_of(annotations["assets"].get(skill["identity_key"], {})))
    if args.json:
        _dump(skill)
        return EXIT_OK
    provenance = skill["provenance"]
    print(f"{skill['name']}  ({skill['dir_name']})")
    print(f"  identity   {skill['identity_key']}")
    print(f"  source     {provenance['label'] or '—'}  [{CONFIDENCE_LABEL.get(provenance['confidence'])}]")
    if provenance["evidence"]:
        print(f"  evidence   {provenance['evidence']}")
    if provenance["path"]:
        print(f"  path       {provenance['path']}")
    print(f"  realpath   {skill['realpath']}")
    print(f"  size       {skill['bytes']} B · {skill['lines']} 行")
    if skill["description"]:
        print(f"  desc       {skill['description'][:120]}")
    print("  placements:")
    for placement in skill["placements"]:
        flag = "link" if placement["is_symlink"] else "dir "
        print(f"    {flag} {placement['kind']:<9} {placement['entry_path']}")
    if skill["issues"]:
        print("  issues:")
        for issue in skill["issues"]:
            print(f"    {issue['kind']}: {issue['detail']}")
    return EXIT_OK


def cmd_health(args: argparse.Namespace) -> int:
    _ensure_index()
    conn = index_mod.connect(index_path())
    try:
        annotations = library.resolved(library.stored(), conn)
        claimed = set(library.claims(annotations["assets"]))
        counts = index_mod.counts(conn, claimed)
        issues = index_mod.list_issues(conn, kind=args.kind, claimed=claimed, limit=args.limit)
        facets = index_mod.facets(conn, annotations["assets"])
    finally:
        conn.close()
    if args.json:
        _dump({"counts": counts, "kinds": HEALTH_KINDS, "facets": facets, "items": issues})
        return EXIT_FINDINGS if issues else EXIT_OK
    print(f"skills {counts['skills']} · placements {counts['placements']} · issues {counts['issues']}")
    for entry in facets["health"]:
        label = HEALTH_KINDS.get(entry["value"], {}).get("label", entry["value"])
        print(f"  {entry['value']:<18} {entry['count']:>4}  {label}")
    if issues:
        print()
        for issue in issues:
            print(f"  [{issue['kind']}] {issue['detail']}")
    return EXIT_FINDINGS if issues else EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    _ensure_index()
    conn = index_mod.connect(index_path())
    try:
        meta = index_mod.meta(conn)
        counts = index_mod.counts(conn, _claims(conn))
        roots = index_mod.list_roots(conn)
    finally:
        conn.close()
    lockfiles = [{"path": str(path), "exists": path.is_file()} for path in lockfile_paths()]
    payload = {
        "version": __version__,
        "config_dir": str(config_dir()),
        "state_dir": str(state_dir()),
        "index": {"path": str(index_path()), "meta": meta, "counts": counts},
        "roots": roots,
        "lockfile": lockfiles,
        "frontend_built": (Path(__file__).resolve().parents[2] / "frontend" / "dist").is_dir(),
    }
    if args.json:
        _dump(payload)
        return EXIT_OK
    print(f"skilldesk {__version__}")
    print(f"  config  {payload['config_dir']}")
    print(f"  state   {payload['state_dir']}")
    print(f"  index   {payload['index']['path']}")
    print(f"  counts  {json.dumps(counts, ensure_ascii=False)}")
    print(f"  frontend built: {payload['frontend_built']}")
    print("  roots:")
    for root in roots:
        mark = "✓" if root["exists"] else "·"
        print(f"    {mark} {root['kind']:<9} {root['entries']:>4}  {root['path']}")
    print("  lockfile:")
    for item in lockfiles:
        mark = "✓" if item["exists"] else "·"
        print(f"    {mark} {item['path']}")
    return EXIT_OK


def _serve(args: argparse.Namespace, open_browser: bool) -> int:
    _ensure_index()
    import uvicorn

    from .server import create_app

    remote = args.host not in {"127.0.0.1", "localhost", "::1"}
    remote_token = os.environ.get("SKILLDESK_REMOTE_TOKEN", "") if remote else ""
    if remote and not (args.allow_remote and remote_token):
        print("远程访问需要 --allow-remote 和 SKILLDESK_REMOTE_TOKEN", file=sys.stderr)
        return EXIT_ERROR
    app = create_app(remote_token=remote_token or None)
    url = f"http://{args.host}:{args.port}/"
    if not open_browser:
        print(f"skilldesk → {url}")
        # proxy_headers stays off: the access guard decides trust from the immediate
        # peer, and uvicorn would otherwise replace that peer with X-Forwarded-For.
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=False)
        return EXIT_OK

    import threading
    import time
    import webbrowser

    # see the note in the serve branch: trust is peer-based, not header-based
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning", proxy_headers=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    print(f"skilldesk → {url}  (Ctrl-C 退出)")
    webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=5)
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    return _serve(args, open_browser=False)


def cmd_open(args: argparse.Namespace) -> int:
    return _serve(args, open_browser=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skilldesk", description="Local-first agent skill manager.")
    parser.add_argument("--version", action="version", version=f"skilldesk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="重建本机索引")
    scan_parser.add_argument("--json", action="store_true")
    scan_parser.set_defaults(func=cmd_scan)

    list_parser = sub.add_parser("list", help="列出 skill")
    list_parser.add_argument("--q", default="")
    list_parser.add_argument("--host", default="", help="按宿主根类型过滤: agents/claude/opencode/project/…")
    list_parser.add_argument("--source", default="", help="按来源过滤: host/repo")
    list_parser.add_argument("--confidence", default="", choices=["", "recorded", "declared", "claimed", "none"])
    list_parser.add_argument("--health", default="", help="按健康问题类型过滤")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    show_parser = sub.add_parser("show", help="查看单个 skill")
    show_parser.add_argument("key")
    show_parser.add_argument("--json", action="store_true")
    show_parser.add_argument("--html", action="store_true", help="输出渲染后的正文 HTML")
    show_parser.set_defaults(func=cmd_show)

    health_parser = sub.add_parser("health", help="安装健康检查")
    health_parser.add_argument("--kind", default="")
    health_parser.add_argument("--limit", type=int, default=50)
    health_parser.add_argument("--json", action="store_true")
    health_parser.set_defaults(func=cmd_health)

    doctor_parser = sub.add_parser("doctor", help="环境与索引自检")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(func=cmd_doctor)

    for name, func, help_text in (
        ("serve", cmd_serve, "常驻启动 HTTP 服务"),
        ("open", cmd_open, "按需启动服务并打开浏览器"),
    ):
        serve_parser = sub.add_parser(name, help=help_text)
        serve_parser.add_argument("--host", default="127.0.0.1")
        serve_parser.add_argument("--allow-remote", action="store_true", help="启用令牌保护的远程访问")
        serve_parser.add_argument("--port", type=int, default=17888)
        serve_parser.set_defaults(func=func)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
