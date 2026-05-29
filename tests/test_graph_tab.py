import tkinter as tk

from llm.graph_data import Node, Edge, Graph
from ui.graph_tab import _force_step, filter_nodes, filter_edges, shortest_path


def test_force_step_converges():
    """Force layout should move nodes at least initially."""
    nodes = [
        {"id": "a", "x": 10.0, "y": 10.0},
        {"id": "b", "x": 90.0, "y": 10.0},
        {"id": "c", "x": 50.0, "y": 90.0},
    ]
    edges = [("a", "b"), ("b", "c")]
    moved = _force_step(nodes, edges, width=200, height=200, temp=1.0)
    assert moved > 0.0


def test_graph_window_creates_toplevel():
    try:
        root = tk.Tk()
    except tk.TclError:
        return  # headless — skip
    root.withdraw()
    try:
        from ui.graph_tab import _GraphWindow
        gw = _GraphWindow(root)
        assert isinstance(gw.win, tk.Toplevel)
        gw.win.destroy()
    finally:
        root.destroy()


# ── Phase 2: filter helper tests ────────────────────────────────────────

def _make_test_graph() -> Graph:
    """Build a small test graph for filter tests."""
    return Graph(
        nodes=[
            Node("entities/a.md", "Alpha", "entity"),
            Node("entities/b.md", "Beta", "entity"),
            Node("concepts/c.md", "Gamma", "concept"),
            Node("sources/d.md", "Delta", "source"),
            Node("entities/e.md", "Epsilon", "entity", exists=False),
        ],
        edges=[
            Edge("entities/a.md", "entities/b.md", "related", True),
            Edge("entities/a.md", "concepts/c.md", "related", False),
            Edge("entities/b.md", "concepts/c.md", "related", True),
        ],
    )


def test_filter_nodes_by_kind():
    g = _make_test_graph()
    visible = filter_nodes(g, kinds={"entity"})
    assert visible == {"entities/a.md", "entities/b.md", "entities/e.md"}


def test_filter_nodes_by_min_degree():
    g = _make_test_graph()
    degrees = {"entities/a.md": 2, "entities/b.md": 2, "concepts/c.md": 2, "sources/d.md": 0, "entities/e.md": 0}
    visible = filter_nodes(g, min_degree=1, degrees=degrees)
    assert "sources/d.md" not in visible
    assert "entities/e.md" not in visible
    assert "entities/a.md" in visible


def test_filter_nodes_by_search():
    g = _make_test_graph()
    visible = filter_nodes(g, search="alpha")
    assert visible == {"entities/a.md"}


def test_filter_nodes_search_path():
    g = _make_test_graph()
    visible = filter_nodes(g, search="concepts/")
    assert visible == {"concepts/c.md"}


def test_filter_nodes_no_filters():
    g = _make_test_graph()
    visible = filter_nodes(g)
    assert len(visible) == 5


def test_filter_edges():
    g = _make_test_graph()
    visible_ids = {"entities/a.md", "entities/b.md", "concepts/c.md"}
    edges = filter_edges(g, visible_ids)
    assert len(edges) == 3  # all 3 edges have both endpoints visible


def test_filter_edges_excludes_partial():
    g = _make_test_graph()
    visible_ids = {"entities/a.md", "entities/b.md"}
    edges = filter_edges(g, visible_ids)
    assert len(edges) == 1  # only a↔b


def test_shortest_path_direct():
    edges = [Edge("a", "b"), Edge("b", "c")]
    path = shortest_path(edges, "a", "b")
    assert path == ["a", "b"]


def test_shortest_path_indirect():
    edges = [Edge("a", "b"), Edge("b", "c"), Edge("c", "d")]
    path = shortest_path(edges, "a", "d")
    assert path == ["a", "b", "c", "d"]


def test_shortest_path_no_path():
    edges = [Edge("a", "b"), Edge("c", "d")]
    path = shortest_path(edges, "a", "d")
    assert path is None


def test_shortest_path_same_node():
    edges = [Edge("a", "b")]
    path = shortest_path(edges, "a", "a")
    assert path == ["a"]
