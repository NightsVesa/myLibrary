import tkinter as tk


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
