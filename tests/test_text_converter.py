from converter.text_converter import text_to_markdown


def test_plain_text_unchanged():
    result = text_to_markdown("hello world")
    assert "hello world" in result


def test_adds_yaml_frontmatter():
    result = text_to_markdown("content", title="My Note")
    assert result.startswith("---")
    assert "title: My Note" in result


def test_empty_string():
    result = text_to_markdown("")
    assert isinstance(result, str)


def test_preserves_existing_newlines():
    result = text_to_markdown("line1\nline2\nline3")
    assert "line1" in result
    assert "line3" in result
