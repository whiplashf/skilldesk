"""A small, dependency-free GFM subset renderer for SKILL.md files.

It is intentionally forgiving: skill documents use headings, fenced code,
tables, quotes and lists, and that is all this renderer needs to handle.
Raw HTML is escaped, links are kept but externalised in the UI.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w#+-]*)\s*$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?[\s:|-]*$")


def esc(value: str) -> str:
    return html.escape(value, quote=False)


def safe_url(url: str) -> bool:
    if not url or url.startswith("//") or "\\" in url or any(ord(ch) < 32 for ch in url):
        return False
    try:
        return urlsplit(url).scheme.lower() in {"", "http", "https", "mailto"}
    except ValueError:
        return False


_INLINE = re.compile(r'\x60([^\x60\n]+)\x60|(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def _emphasis(text: str) -> str:
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", esc(text))
    return re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)


def inline(text: str) -> str:
    parts: list[str] = []
    start = 0
    for match in _INLINE.finditer(text):
        parts.append(_emphasis(text[start:match.start()]))
        code, image, label, url = match.groups()
        if code is not None:
            parts.append(f"<code>{esc(code)}</code>")
        elif not safe_url(url):
            parts.append(esc(label))
        elif image:
            parts.append(f'<img alt="{html.escape(label, quote=True)}" src="{html.escape(url, quote=True)}">')
        else:
            parts.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{_emphasis(label)}</a>')
        start = match.end()
    parts.append(_emphasis(text[start:]))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]


def render_table(rows: list[str]) -> str:
    head = _cells(rows[0])
    aligns = []
    for cell in _cells(rows[1]):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left")

    def align(index: int) -> str:
        return aligns[index] if index < len(aligns) else "left"

    out = ["<table><thead><tr>"]
    for index, cell in enumerate(head):
        out.append(f'<th style="text-align:{align(index)}">{inline(cell)}</th>')
    out.append("</tr></thead><tbody>")
    for row in rows[2:]:
        cells = _cells(row)
        out.append("<tr>")
        for index in range(len(head)):
            value = cells[index] if index < len(cells) else ""
            out.append(f'<td style="text-align:{align(index)}">{inline(value)}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def render_list(items: list[tuple[int, str]]) -> str:
    out = ['<ul class="md-list">']
    for depth, text in items:
        out.append(f'<li class="d{min(depth, 3)}">{inline(text)}</li>')
    out.append("</ul>")
    return "".join(out)


def render(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, total = 0, len(lines)
    while i < total:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(2)
            lang = fence.group(3)
            i += 1
            buf = []
            closing = re.compile(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$")
            while i < total and not closing.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{esc(chr(10).join(buf))}</code></pre>")
            continue

        heading = HEAD_RE.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if i + 1 < total and "|" in line and TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            rows = [line, lines[i + 1]]
            i += 2
            while i < total and lines[i].strip() and "|" in lines[i]:
                rows.append(lines[i])
                i += 1
            out.append(render_table(rows))
            continue

        if line.lstrip().startswith(">"):
            buf = []
            while i < total and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render(chr(10).join(buf))}</blockquote>")
            continue

        listed = UL_RE.match(line) or OL_RE.match(line)
        if listed:
            items: list[tuple[int, str]] = []
            base = len(listed.group(1).expandtabs(4))
            while i < total:
                item = UL_RE.match(lines[i]) or OL_RE.match(lines[i])
                if item:
                    indent = len(item.group(1).expandtabs(4))
                    items.append((max(0, (indent - base) // 2), item.group(2)))
                    i += 1
                elif lines[i].strip() and items and not re.match(r"^\s*([-*+]|\d+[.)])\s", lines[i]) and not HEAD_RE.match(lines[i]):
                    items[-1] = (items[-1][0], items[-1][1] + " " + lines[i].strip())
                    i += 1
                else:
                    break
            out.append(render_list(items))
            continue

        buf = []
        while i < total and lines[i].strip():
            current = lines[i]
            if FENCE_RE.match(current) or HEAD_RE.match(current) or UL_RE.match(current) or OL_RE.match(current) or current.lstrip().startswith(">"):
                break
            buf.append(current)
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(part.strip() for part in buf))}</p>")
        else:
            out.append(f"<p>{inline(line.strip())}</p>")
            i += 1
    return "\n".join(out)


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    data: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []
    for line in raw.splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match and not line.startswith((" ", "\t")):
            if key:
                data[key] = "\n".join(buf).strip()
            key, rest = match.group(1), match.group(2)
            buf = [] if rest in ("|", ">", "|-", ">-", "") else [rest.strip("\"'")]
        elif key and not line.startswith((" ", "\t")):
            continue
        elif key:
            buf.append(line.strip())
    if key:
        data[key] = "\n".join(buf).strip()
    return data, text[end + 4 :]


_BOILERPLATE = (
    r"(?i)^this skill should be used when the user (?:asks|wants|requests|mentions|says|is)\s*(?:to|for|about)?\s*",
    r"(?i)^this skill should be used (?:when|for)\s*(?:the user\s*)?",
    r"(?i)^use this skill (?:when|for)\s*(?:the user\s*)?",
    r"(?i)^use when\s*(?:the user\s*)?",
    r"(?i)^use this when\s*(?:the user\s*)?",
    r"(?i)^trigger(?:s)? when\s*(?:the user\s*)?",
)


def clean_description(description: str) -> str:
    """Drop the boilerplate lead-in that most SKILL.md descriptions share."""
    if not description:
        return description
    for pattern in _BOILERPLATE:
        stripped = re.sub(pattern, "", description)
        if stripped != description:
            description = stripped
            break
    description = description.strip()
    if description and description[0].isalpha() and description[0].islower():
        description = description[0].upper() + description[1:]
    return description
