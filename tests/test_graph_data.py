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
        "- [OpenAI](../entities/openai.md)\n"
        "- [ML](../concepts/ml.md)\n",
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


def test_parse_wiki_graph_entity_related_edges(mini_wiki):
    """Entity pages with ## Related produce edges in the graph."""
    (mini_wiki / "entities" / "openai.md").write_text(
        "# OpenAI\n\nAI lab.\n\n## Related\n\n"
        "- [ML](../concepts/ml.md)\n"
        "- [DeepSeek](deepseek.md)\n",
        encoding="utf-8",
    )
    g = parse_wiki_graph(mini_wiki)
    edge_keys = {(e.source, e.target) for e in g.edges}
    assert ("sources/summary_a.md", "entities/openai.md") in edge_keys
    assert ("entities/openai.md", "concepts/ml.md") in edge_keys
    assert ("entities/openai.md", "entities/deepseek.md") in edge_keys


# ── Phase 1: data enrichment tests ──────────────────────────────────────

def test_relative_links_resolved(tmp_path):
    """Relative links like ../concepts/foo.md should be resolved."""
    w = tmp_path / "wiki"
    (w / "sources").mkdir(parents=True)
    (w / "concepts").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Sources\n- [My Source](sources/my_source.md)\n"
        "## Concepts\n- [Foo](concepts/foo.md)\n",
        encoding="utf-8",
    )
    (w / "sources" / "my_source.md").write_text(
        "# My Source\n\n## Related\n\n- [Foo](../concepts/foo.md)\n",
        encoding="utf-8",
    )
    (w / "concepts" / "foo.md").write_text("# Foo\n", encoding="utf-8")

    g = parse_wiki_graph(w)
    edge_ids = [(e.source, e.target) for e in g.edges]
    assert ("sources/my_source.md", "concepts/foo.md") in edge_ids


def test_duplicate_related_links_deduplicated(tmp_path):
    """Duplicate related links produce only one edge."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [A](entities/a.md)\n- [B](entities/b.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "a.md").write_text(
        "# A\n\n## Related\n\n- [B](b.md)\n- [B](b.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "b.md").write_text("# B\n", encoding="utf-8")

    g = parse_wiki_graph(w)
    a_to_b = [e for e in g.edges if e.source == "entities/a.md" and e.target == "entities/b.md"]
    assert len(a_to_b) == 1


def test_bidirectional_edge_detection(tmp_path):
    """Edge is bidirectional when both pages link to each other."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [X](entities/x.md)\n- [Y](entities/y.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "x.md").write_text(
        "# X\n\n## Related\n\n- [Y](y.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "y.md").write_text(
        "# Y\n\n## Related\n\n- [X](x.md)\n",
        encoding="utf-8",
    )

    g = parse_wiki_graph(w)
    x_to_y = [e for e in g.edges if e.source == "entities/x.md" and e.target == "entities/y.md"]
    assert len(x_to_y) == 1
    assert x_to_y[0].bidirectional is True


def test_one_way_edge_not_bidirectional(tmp_path):
    """Edge is not bidirectional when only one side links."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [P](entities/p.md)\n- [Q](entities/q.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "p.md").write_text(
        "# P\n\n## Related\n\n- [Q](q.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "q.md").write_text("# Q\n", encoding="utf-8")

    g = parse_wiki_graph(w)
    p_to_q = [e for e in g.edges if e.source == "entities/p.md" and e.target == "entities/q.md"]
    assert len(p_to_q) == 1
    assert p_to_q[0].bidirectional is False


def test_missing_file_node_exists_false(tmp_path):
    """Nodes indexed but missing from disk have exists=False."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [Ghost](entities/ghost.md)\n",
        encoding="utf-8",
    )
    # Do NOT create entities/ghost.md

    g = parse_wiki_graph(w)
    ghost = [n for n in g.nodes if n.id == "entities/ghost.md"]
    assert len(ghost) == 1
    assert ghost[0].exists is False
    assert ghost[0].mtime == 0.0


def test_node_metadata_populated(tmp_path):
    """Existing nodes get path, summary, mtime, exists=True."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [Test](entities/test.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "test.md").write_text(
        "---\nkey: value\n---\n# Test Entity\nThis is a useful summary paragraph.\n",
        encoding="utf-8",
    )

    g = parse_wiki_graph(w)
    node = [n for n in g.nodes if n.id == "entities/test.md"][0]
    assert node.exists is True
    assert node.mtime > 0
    assert node.path == "entities/test.md"
    assert "useful summary" in node.summary


def test_edge_kind_defaults_to_related(tmp_path):
    """All edges from ## Related have kind='related'."""
    w = tmp_path / "wiki"
    (w / "entities").mkdir(parents=True)
    (w / "index.md").write_text(
        "## Entities\n- [A](entities/a.md)\n- [B](entities/b.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "a.md").write_text(
        "# A\n\n## Related\n\n- [B](b.md)\n",
        encoding="utf-8",
    )
    (w / "entities" / "b.md").write_text("# B\n", encoding="utf-8")

    g = parse_wiki_graph(w)
    assert all(e.kind == "related" for e in g.edges)


def test_backward_compatible_fields(mini_wiki):
    """Node and Edge basic fields (id, title, kind, source, target) still work."""
    g = parse_wiki_graph(mini_wiki)
    assert len(g.nodes) == 4
    n = g.nodes[0]
    assert n.id == "sources/summary_a.md"
    assert n.title == "Note A"
    assert n.kind == "source"
