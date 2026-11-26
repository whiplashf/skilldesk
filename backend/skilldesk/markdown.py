"""A small, dependency-free GFM subset renderer for SKILL.md files.

It is intentionally forgiving: skill documents use headings, fenced code,
tables, quotes and lists, and that is all this renderer needs to handle.
Raw HTML is escaped, links are kept but externalised in the UI.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

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


def inline(text: str, base_url: str = "") -> str:
    parts: list[str] = []
    start = 0
    for match in _INLINE.finditer(text):
        parts.append(_emphasis(text[start:match.start()]))
        code, image, label, url = match.groups()
        if code is not None:
            parts.append(f"<code>{esc(code)}</code>")
        elif not safe_url(url):
            parts.append(esc(label))
        elif image and not base_url:
            alt = html.escape(label, quote=True)
            value = html.escape(url, quote=True)
            if urlsplit(url).scheme.lower() in {"http", "https"}:
                parts.append(f'<button type="button" data-remote-image="{value}" data-alt="{alt}">'
                             f'加载外部图片{(" · " + esc(label)) if label else ""}</button>')
            elif not urlsplit(url).scheme:
                parts.append(f'<img alt="{alt}" src="{value}">')
            else:
                parts.append(esc(label))
        else:
            href = html.escape(urljoin(base_url, url) if base_url else url, quote=True)
            caption = _emphasis(label or ("查看图片" if image else ""))
            parts.append(f'<a href="{href}" target="_blank" rel="noreferrer">{caption}</a>')
        start = match.end()
    parts.append(_emphasis(text[start:]))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]


def render_table(rows: list[str], base_url: str = "") -> str:
    head = _cells(rows[0])
    aligns = []
    for cell in _cells(rows[1]):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left")

    def align(index: int) -> str:
        return aligns[index] if index < len(aligns) else "left"

    out = ["<table><thead><tr>"]
    for index, cell in enumerate(head):
        out.append(f'<th style="text-align:{align(index)}">{inline(cell, base_url)}</th>')
    out.append("</tr></thead><tbody>")
    for row in rows[2:]:
        cells = _cells(row)
        out.append("<tr>")
        for index in range(len(head)):
            value = cells[index] if index < len(cells) else ""
            out.append(f'<td style="text-align:{align(index)}">{inline(value, base_url)}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def strip_indent(line: str, columns: int) -> str | None:
    """Remove structural indentation while preserving tabs and spaces inside the block."""
    prefix = spaces = 0
    while prefix < len(line) and line[prefix] in " \t" and spaces < columns:
        spaces += 1 if line[prefix] == " " else 4 - spaces % 4
        prefix += 1
    return " " * (spaces - columns) + line[prefix:] if spaces >= columns else None


def render_list(lines: list[str], start: int, depth: int, base_url: str = "") -> tuple[str, int]:
    first = lines[start].expandtabs(4)
    pattern = OL_RE if OL_RE.match(first) else UL_RE
    marker = pattern.match(first)
    indent = len(marker[1])
    tag = "ol" if pattern is OL_RE else "ul"
    number = re.match(r"\d+", first.lstrip()) if tag == "ol" else None
    initial = f' start="{number[0]}"' if number and number[0] != "1" else ""
    out = [f'<{tag} class="md-list"{initial}>']
    i = start
    while i < len(lines):
        item = pattern.match(lines[i])
        if not item or len(item[1].expandtabs(4)) != indent:
            break
        body = [item[2]]
        width = len(lines[i][:item.start(2)].expandtabs(4))
        i += 1
        while i < len(lines):
            line = lines[i]
            content = strip_indent(line, width)
            if content is not None:
                body.append(content)
            elif not line.strip():
                body.append("")
            elif (body[-1].strip() and not FENCE_RE.match(body[-1]) and not FENCE_RE.match(line)
                  and not (HEAD_RE.match(line) or UL_RE.match(line) or OL_RE.match(line) or HR_RE.match(line))
                  and not line.lstrip().startswith(">")):
                body.append(line)
            else:
                break
            i += 1
        out.append("<li>" + render("\n".join(body), base_url=base_url, _depth=depth + 1) + "</li>")
    return "".join(out) + f"</{tag}>", i


def render(markdown: str, *, base_url: str = "", _depth: int = 0) -> str:
    if _depth >= 48:
        return "<pre>" + esc(markdown) + "</pre>"
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, total = 0, len(lines)
    while i < total:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if strip_indent(line, 4) is not None:
            buf = []
            while i < total:
                content = strip_indent(lines[i], 4)
                if content is None and lines[i].strip():
                    break
                buf.append(content or "")
                i += 1
            while buf and not buf[-1]:
                buf.pop()
            out.append(f"<pre><code>{esc(chr(10).join(buf))}</code></pre>")
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
            out.append(f"<h{level}>{inline(heading.group(2), base_url)}</h{level}>")
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
            out.append(render_table(rows, base_url))
            continue

        if line.lstrip().startswith(">"):
            buf = []
            while i < total and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render(chr(10).join(buf), base_url=base_url, _depth=_depth + 1)}</blockquote>")
            continue

        listed = UL_RE.match(line) or OL_RE.match(line)
        if listed:
            html_list, i = render_list(lines, i, _depth, base_url)
            out.append(html_list)
            continue

        buf = []
        while i < total and lines[i].strip():
            current = lines[i]
            if FENCE_RE.match(current) or HEAD_RE.match(current) or UL_RE.match(current) or OL_RE.match(current) or current.lstrip().startswith(">"):
                break
            buf.append(current)
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(part.strip() for part in buf), base_url)}</p>")
        else:
            out.append(f"<p>{inline(line.strip(), base_url)}</p>")
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
