import pytest
from pathlib import Path
from llm.graph_data import parse_wiki_graph, Graph, Node, Edge


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    """Set up a tiny synthetic wiki in a temp directory."""
    w = tmp_path / "wiki"
    w.mkdir()
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir()

    # index.md
    (w / "index.md").write_text(
        "# Wiki Index\n\n"
        "## Sources\n"
        "- [Note A](sources/summary_a.md) — a\n"
        "## Entities\n"
        "- [OpenAI](entities/openai.md) — AI lab\n"
        "- [DeepSeek](entities/deepseek.md) — AI lab\n"
        "## Concepts\n"
        "- [ML](concepts/ml.md) — machine learning\n",
        encoding="utf-8",
    )

    # Source page with Related links
    (w / "sources" / "summary_a.md").write_text(
        "# Note A\n\nContent.\n\n"
        "## Related\n\n"
        "- [OpenAI](entities/openai.md)\n"
        "- [ML](concepts/ml.md)\n",
        encoding="utf-8",
    )

    # Entity page (optional — some pages exist without sources)
    (w / "entities" / "openai.md").write_text("# OpenAI\n\nAI lab.\n", encoding="utf-8")
    (w / "entities" / "deepseek.md").write_text("# DeepSeek\n\nAI lab.\n", encoding="utf-8")
    (w / "concepts" / "ml.md").write_text("# ML\n\nField.\n", encoding="utf-8")
    return w


def test_parse_wiki_graph_nodes(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    nodes = {n.id for n in g.nodes}
    assert "sources/summary_a.md" in nodes
    assert "entities/openai.md" in nodes
    assert "entities/deepseek.md" in nodes
    assert "concepts/ml.md" in nodes
    # DeepSeek is in index but has no edges → still a node
    assert len(g.nodes) == 4


def test_parse_wiki_graph_node_types(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    by_type = {}
    for n in g.nodes:
        by_type.setdefault(n.kind, []).append(n.id)
    assert len(by_type["source"]) == 1
    assert len(by_type["entity"]) == 2
    assert len(by_type["concept"]) == 1


def test_parse_wiki_graph_edges(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    edge_keys = {(e.source, e.target) for e in g.edges}
    assert ("sources/summary_a.md", "entities/openai.md") in edge_keys
    assert ("sources/summary_a.md", "concepts/ml.md") in edge_keys
    assert len(g.edges) == 2  # DeepSeek has no incoming edges


def test_parse_wiki_graph_no_related_section(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    (w / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n"
        "## Concepts\n_(none yet)_\n",
        encoding="utf-8",
    )
    (w / "sources" / "summary_a.md").write_text("# A\n\nNo Related section.\n", encoding="utf-8")
    g = parse_wiki_graph(w)
    assert len(g.nodes) >= 1
    assert len(g.edges) == 0


def test_parse_wiki_graph_empty_wiki(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    (w / "index.md").write_text("## Sources\n_(none yet)_\n\n## Entities\n_(none yet)_\n\n## Concepts\n_(none yet)_\n", encoding="utf-8")
    g = parse_wiki_graph(w)
    assert len(g.nodes) == 0
    assert len(g.edges) == 0
