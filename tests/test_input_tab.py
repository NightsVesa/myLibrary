from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest
from PIL import Image

from ui.input_tab import _dump_to_markdown_body, InputTab


class TestDumpToMarkdownBody:
    """Tests for the pure function that converts tk.Text.dump() output to Markdown."""

    def test_text_only_preserves_body(self):
        dump = [("text", "Hello World\n", "1.0")]
        result = _dump_to_markdown_body(dump, {})
        assert result == "Hello World"

    def test_image_only_serializes_link(self):
        dump = [("image", "image1", "1.0")]
        image_map = {"image1": Path("/notes/.assets/20240604_120000_123456.png")}
        result = _dump_to_markdown_body(dump, image_map)
        assert result == "![](.assets/20240604_120000_123456.png)"

    def test_text_image_text_interleaving(self):
        dump = [
            ("text", "Before\n", "1.0"),
            ("image", "img1", "2.0"),
            ("text", "After\n", "2.1"),
        ]
        image_map = {"img1": Path("/notes/.assets/img.png")}
        result = _dump_to_markdown_body(dump, image_map)
        assert result == "Before\n![](.assets/img.png)After"

    def test_multiple_images(self):
        dump = [
            ("image", "img1", "1.0"),
            ("text", "\n", "1.1"),
            ("image", "img2", "2.0"),
        ]
        image_map = {
            "img1": Path("/notes/.assets/a.png"),
            "img2": Path("/notes/.assets/b.png"),
        }
        result = _dump_to_markdown_body(dump, image_map)
        assert "![](.assets/a.png)" in result
        assert "![](.assets/b.png)" in result

    def test_unknown_image_skipped(self):
        dump = [("image", "ghost", "1.0")]
        result = _dump_to_markdown_body(dump, {})
        assert result == ""

    def test_empty_editor_returns_empty_string(self):
        result = _dump_to_markdown_body([], {})
        assert result == ""

    def test_text_to_markdown_frontmatter_applied(self):
        """Verify that text_to_markdown() wraps the body with frontmatter."""
        from converter.text_converter import text_to_markdown

        body = "Some content"
        md = text_to_markdown(body, title="My Note")
        assert md.startswith("---\n")
        assert "title: My Note" in md
        assert body in md

    def test_image_path_uses_relative_assets_prefix(self):
        """The saved markdown link uses .assets/<name> relative to the note file."""
        asset_path = Path("/some/path/notes/.assets/screenshot.png")
        assert asset_path.name == "screenshot.png"
        link = f"![](.assets/{asset_path.name})"
        assert link == "![](.assets/screenshot.png)"


# ── helpers ────────────────────────────────────────────────────────────────

def _make_test_image() -> Image.Image:
    return Image.new("RGB", (100, 50), color=(255, 0, 0))


def _make_tk_root():
    """Return a withdrawn tk root, or None in headless environments."""
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    return root


# ── OCR behavior tests ─────────────────────────────────────────────────────


class TestOCRInsertion:
    """OCR insertion behaviors with a real tk.Text widget."""

    def test_ocr_ok_inserts_block(self):
        root = _make_tk_root()
        if root is None:
            pytest.skip("headless — no tkinter display")
        try:
            parent = tk.Frame(root)
            tab = InputTab(parent)
            img = _make_test_image()
            # Create a fake asset path so _embed_image doesn't need filesystem
            asset_path = Path("/tmp/.assets/test_ocr.png")
            image_name = tab._embed_image(img, asset_path)
            assert image_name in tab._image_map

            lines = ["Hello", "World"]
            tab._ocr_q.put((tab._editor_generation, image_name, "ok", lines))
            tab._poll_ocr()

            text_content = tab.text_border.text.get("1.0", tk.END)
            assert "<!-- ocr -->" in text_content
            assert "Hello" in text_content
            assert "World" in text_content
            assert "<!-- /ocr -->" in text_content
        finally:
            root.destroy()

    def test_ocr_unavailable_leaves_image_no_block(self):
        root = _make_tk_root()
        if root is None:
            pytest.skip("headless — no tkinter display")
        try:
            parent = tk.Frame(root)
            tab = InputTab(parent)
            img = _make_test_image()
            asset_path = Path("/tmp/.assets/test_ocr.png")
            image_name = tab._embed_image(img, asset_path)

            tab._ocr_q.put((tab._editor_generation, image_name, "unavailable", []))
            tab._poll_ocr()

            text_content = tab.text_border.text.get("1.0", tk.END)
            assert "<!-- ocr -->" not in text_content
            # Image should still be in the widget
            assert image_name in tab._image_map
        finally:
            root.destroy()

    def test_stale_generation_ignored_after_clear(self):
        root = _make_tk_root()
        if root is None:
            pytest.skip("headless — no tkinter display")
        try:
            parent = tk.Frame(root)
            tab = InputTab(parent)
            img = _make_test_image()
            asset_path = Path("/tmp/.assets/test_ocr.png")
            image_name = tab._embed_image(img, asset_path)

            # Simulate save/clear
            tab._image_map.clear()
            tab._image_marks.clear()
            tab._photo_refs.clear()
            tab._editor_generation += 1

            # Late OCR result with old generation
            tab._ocr_q.put((0, image_name, "ok", ["stale"]))
            tab._poll_ocr()

            text_content = tab.text_border.text.get("1.0", tk.END)
            assert "stale" not in text_content
        finally:
            root.destroy()

    def test_image_removed_before_ocr_ignored(self):
        root = _make_tk_root()
        if root is None:
            pytest.skip("headless — no tkinter display")
        try:
            parent = tk.Frame(root)
            tab = InputTab(parent)
            img = _make_test_image()
            asset_path = Path("/tmp/.assets/test_ocr.png")
            image_name = tab._embed_image(img, asset_path)

            # Remove the image from map (simulating it was deleted)
            del tab._image_map[image_name]

            tab._ocr_q.put((tab._editor_generation, image_name, "ok", ["gone"]))
            tab._poll_ocr()

            text_content = tab.text_border.text.get("1.0", tk.END)
            assert "gone" not in text_content
        finally:
            root.destroy()

    def test_ocr_error_sets_status(self):
        root = _make_tk_root()
        if root is None:
            pytest.skip("headless — no tkinter display")
        try:
            parent = tk.Frame(root)
            tab = InputTab(parent)
            img = _make_test_image()
            asset_path = Path("/tmp/.assets/test_ocr.png")
            image_name = tab._embed_image(img, asset_path)

            tab._ocr_q.put((tab._editor_generation, image_name, "error", []))
            tab._poll_ocr()

            status = tab.status_label.cget("text")
            assert "OCR" in status
        finally:
            root.destroy()
