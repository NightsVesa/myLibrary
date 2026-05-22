import tkinter as tk
from pathlib import Path
from llm.graph_data import Graph, Node, Edge

# GraphTab requires a running tk root, so we test the layout logic directly.


def test_force_step_converges():
    """Force layout should move nodes at least initially."""
    from ui.graph_tab import _force_step
    nodes = [
        {"id": "a", "x": 10.0, "y": 10.0},
        {"id": "b", "x": 90.0, "y": 10.0},
        {"id": "c", "x": 50.0, "y": 90.0},
    ]
    edges = [("a", "b"), ("b", "c")]
    moved = _force_step(nodes, edges, width=200, height=200, temp=1.0)
    assert moved > 0.0


def test_graph_tab_creates_frame():
    root = tk.Tk()
    root.withdraw()
    try:
        from ui.graph_tab import GraphTab
        tab = GraphTab(root)
        assert isinstance(tab.frame, tk.Frame)
    finally:
        root.destroy()
