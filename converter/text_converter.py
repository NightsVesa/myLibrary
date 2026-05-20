from datetime import datetime


def text_to_markdown(text: str, title: str | None = None) -> str:
    """Wrap plain text in Markdown with optional YAML front-matter."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_title = title or "Untitled"
    frontmatter = f"---\ntitle: {safe_title}\ncreated: {timestamp}\n---\n\n"
    return frontmatter + text
