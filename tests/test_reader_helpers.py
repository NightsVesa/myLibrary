from ui.search_tab import _middle_ellipsis, extract_markdown_headings


def test_extract_markdown_headings_skips_frontmatter_and_code():
    source = """---
title: Demo
---
# Real

```md
# In code
```

## Child
"""

    assert extract_markdown_headings(source) == [(1, "Real"), (2, "Child")]


def test_middle_ellipsis_preserves_start_and_end():
    text = "D:/very/long/path/to/a/markdown/file.md"
    result = _middle_ellipsis(text, 18)

    assert len(result) <= 18
    assert result.startswith("D:/")
    assert result.endswith("file.md")
    assert "..." in result
