"""Tiny Markdown → tk.Text renderer.

Renders the most common Markdown constructs as styled tags inside a
`tk.Text` widget, *omitting the syntax characters themselves* so the
result reads like a formatted document rather than raw source.

Supported (block):
- ATX headings  `# … ######`  →  h1 … h6
- Code fences   ```` ``` ```` →  code_block
- Blockquote    `> …`         →  blockquote (with left bar marker)
- Unordered list `- ` / `* ` / `+ ` → bulleted item (•)
- Ordered list   `1.`         → numbered item
- Horizontal rule `---` / `***` / `___` → long em-dash run

Supported (inline):
- Bold-italic  `***x***` / `___x___`
- Bold         `**x**`   / `__x__`
- Italic       `*x*`     / `_x_`
- Inline code  `` `x` ``
- Link         `[text](url)`

The caller is expected to pre-configure the following tags on the
target widget (font / colour / background as desired):

    h1 h2 h3 h4 h5 h6 bold italic bold_italic code code_block
    list_bullet blockquote blockquote_marker hr link frontmatter
"""
from __future__ import annotations

import re
import tkinter as tk

# ── inline patterns ────────────────────────────────────────────────────────
# Ordered by greediness (longest markers first) so e.g. `***x***`
# is matched as bold-italic, not bold-then-italic.
_INLINE = [
    (re.compile(r"\*\*\*(.+?)\*\*\*"), "bold_italic"),
    (re.compile(r"___(.+?)___"),         "bold_italic"),
    (re.compile(r"\*\*(.+?)\*\*"),       "bold"),
    (re.compile(r"__(.+?)__"),           "bold"),
    # `*x*` italic: forbid `*` on either side (so it doesn't compete with `**`).
    # No \w lookbehind because Chinese chars count as \w and would block matches.
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), "italic"),
    (re.compile(r"(?<!_)_([^_\n]+?)_(?!_)"),     "italic"),
    (re.compile(r"`([^`\n]+?)`"),        "code"),
    # Link [text](url) — show only `text`
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), "link"),
]

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
_RE_UL = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_RE_OL = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_RE_BLOCKQUOTE = re.compile(r"^>\s?(.*)$")


def render_markdown_into(text: tk.Text, source: str) -> None:
    """Append rendered markdown to `text` at the current insertion point.

    Caller is responsible for clearing the widget and writing any header
    *before* invoking this.
    """
    in_codeblock = False
    in_frontmatter = False
    code_lang = ""

    lines = source.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()

        # YAML front-matter: --- ... ---  at top of file
        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            else:
                text.insert(tk.END, line + "\n", "frontmatter")
            continue

        # Code fence
        if stripped.startswith("```"):
            in_codeblock = not in_codeblock
            code_lang = stripped[3:].strip() if in_codeblock else ""
            if not in_codeblock:
                # add a blank line after the block ends
                text.insert(tk.END, "\n")
            continue
        if in_codeblock:
            text.insert(tk.END, line + "\n", "code_block")
            continue

        # Horizontal rule
        if _RE_HR.match(stripped):
            text.insert(tk.END, "─" * 36 + "\n", "hr")
            continue

        # Heading
        m = _RE_HEADING.match(line)
        if m:
            level = len(m.group(1))
            tag = f"h{min(level, 6)}"
            _insert_inline(text, m.group(2), base_tag=tag)
            text.insert(tk.END, "\n")
            continue

        # Blockquote
        m = _RE_BLOCKQUOTE.match(stripped)
        if m:
            text.insert(tk.END, "▎  ", "blockquote_marker")
            _insert_inline(text, m.group(1), base_tag="blockquote")
            text.insert(tk.END, "\n")
            continue

        # Unordered list
        m = _RE_UL.match(line)
        if m:
            indent, _marker, content = m.group(1), m.group(2), m.group(3)
            text.insert(tk.END, f"{indent}•  ", "list_bullet")
            _insert_inline(text, content)
            text.insert(tk.END, "\n")
            continue

        # Ordered list
        m = _RE_OL.match(line)
        if m:
            indent, num, content = m.group(1), m.group(2), m.group(3)
            text.insert(tk.END, f"{indent}{num}.  ", "list_bullet")
            _insert_inline(text, content)
            text.insert(tk.END, "\n")
            continue

        # Plain paragraph (possibly with inline markup)
        _insert_inline(text, line)
        text.insert(tk.END, "\n")


def _insert_inline(text: tk.Text, line: str, *, base_tag: str | None = None) -> None:
    """Insert `line` into `text` with inline markdown parsed into tags.

    Matches the *earliest* of any inline pattern and consumes it; repeats
    until the line is exhausted.  Matched content is inserted with the
    pattern's tag (plus the optional base_tag from the surrounding block).
    """
    pos = 0
    while pos < len(line):
        earliest = None
        for pat, tag in _INLINE:
            m = pat.search(line, pos)
            if not m:
                continue
            if earliest is None or m.start() < earliest[0].start():
                earliest = (m, tag)
        if earliest is None:
            tags = (base_tag,) if base_tag else ()
            text.insert(tk.END, line[pos:], tags)
            return
        m, tag = earliest
        if m.start() > pos:
            tags = (base_tag,) if base_tag else ()
            text.insert(tk.END, line[pos:m.start()], tags)
        # Content to display = group(1) for all our patterns
        content = m.group(1)
        tags = tuple(t for t in (base_tag, tag) if t)
        start_idx = text.index(tk.END)
        text.insert(tk.END, content, tags)
        # Store URL for link tags so clicks can navigate.
        if tag == "link" and m.lastindex and m.lastindex >= 2:
            end_idx = text.index(tk.END)
            link_map = getattr(text, "_link_map", None)
            if link_map is None:
                link_map = {}
                text._link_map = link_map
            link_map[(start_idx, end_idx)] = m.group(2)
        pos = m.end()


def configure_markdown_tags(text: tk.Text, base_size: int = 10) -> None:
    """Pre-configure all markdown render tags on a tk.Text widget.

    Call once per widget before using render_markdown_into().
    """
    SKY_DARK = "#6D28D9"
    TEXT_LIGHT = "#6B7280"
    SKY_LIGHT = "#E5E7EB"
    s = base_size

    text.tag_config("h1", font=("Microsoft YaHei", s + 5, "bold"),
                    foreground=SKY_DARK, spacing1=8, spacing3=4)
    text.tag_config("h2", font=("Microsoft YaHei", s + 3, "bold"),
                    foreground=SKY_DARK, spacing1=6, spacing3=3)
    text.tag_config("h3", font=("Microsoft YaHei", s + 2, "bold"),
                    foreground=SKY_DARK, spacing1=4, spacing3=2)
    text.tag_config("h4", font=("Microsoft YaHei", s + 1, "bold"),
                    foreground=SKY_DARK)
    text.tag_config("h5", font=("Microsoft YaHei", s, "bold"),
                    foreground=SKY_DARK)
    text.tag_config("h6", font=("Microsoft YaHei", s, "bold"),
                    foreground=TEXT_LIGHT)
    text.tag_config("bold",        font=("Microsoft YaHei", s, "bold"))
    text.tag_config("italic",      font=("Microsoft YaHei", s, "italic"))
    text.tag_config("bold_italic", font=("Microsoft YaHei", s, "bold", "italic"))
    text.tag_config("code", font=("Consolas", max(9, s - 1)),
                    background="#F5F3FF", foreground="#5B21B6")
    text.tag_config("code_block", font=("Consolas", max(9, s - 1)),
                    background="#F5F3FF", foreground="#4C1D95",
                    lmargin1=14, lmargin2=14, spacing1=2, spacing3=2)
    text.tag_config("list_bullet", foreground=SKY_DARK,
                    font=("Microsoft YaHei", s, "bold"))
    text.tag_config("blockquote_marker", foreground=SKY_DARK,
                    font=("Microsoft YaHei", s, "bold"))
    text.tag_config("blockquote", foreground=TEXT_LIGHT,
                    font=("Microsoft YaHei", s, "italic"),
                    lmargin1=4, lmargin2=14)
    text.tag_config("hr", foreground=SKY_LIGHT, font=("Consolas", 8),
                    spacing1=4, spacing3=4, justify="center")
    text.tag_config("link", foreground=SKY_DARK, underline=True)
    text.tag_config("frontmatter", foreground=TEXT_LIGHT,
                    font=("Consolas", 9), lmargin1=4, lmargin2=4)


def highlight_query(text: tk.Text, needle: str, *, tag: str = "hit") -> None:
    """Add `tag` to every occurrence of `needle` (case-insensitive)."""
    if not needle:
        return
    n_low = needle.lower()
    full = text.get("1.0", tk.END)
    full_low = full.lower()
    idx = 0
    while True:
        found = full_low.find(n_low, idx)
        if found == -1:
            break
        text.tag_add(tag, f"1.0 + {found} chars", f"1.0 + {found + len(needle)} chars")
        idx = found + len(needle)
