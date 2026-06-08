from pathlib import Path
import os
import sys
import warnings

import pytest
from PIL import Image

from converter import ocr_converter
from converter.ocr_converter import (
    OCRUnavailableError,
    enrich_markdown_images,
    image_to_markdown,
    is_image_file,
)


def _write_image(path: Path) -> Path:
    Image.new("RGB", (10, 10), "white").save(path)
    return path


def test_is_image_file():
    assert is_image_file(Path("a.png"))
    assert is_image_file(Path("a.JPG"))
    assert not is_image_file(Path("a.md"))


def test_quiet_paddle_init_suppresses_known_noise(capfd):
    with ocr_converter._quiet_paddle_init():
        warnings.warn(
            "No ccache found. Please be aware that recompiling all source files may be required.",
            UserWarning,
        )
        warnings.warn(
            "urllib3 (2.6.3) or chardet (7.4.3)/charset_normalizer (3.4.6) doesn't match a supported version!",
            Warning,
        )
        os.write(2, "信息: 用提供的模式无法找到文件。\n".encode("utf-8"))

    _out, err = capfd.readouterr()
    assert "ccache" not in err
    assert "urllib3" not in err
    assert "用提供的模式无法找到文件" not in err


def test_bundled_ocr_model_dirs_uses_pyinstaller_models(tmp_path, monkeypatch):
    root = tmp_path / ".paddleocr" / "whl"
    for model_dir in (
        root / "det" / "ch" / "ch_PP-OCRv4_det_infer",
        root / "rec" / "ch" / "ch_PP-OCRv4_rec_infer",
        root / "cls" / "ch_ppocr_mobile_v2.0_cls_infer",
    ):
        model_dir.mkdir(parents=True)

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    dirs = ocr_converter._bundled_ocr_model_dirs()

    assert dirs["det_model_dir"].endswith("ch_PP-OCRv4_det_infer")
    assert dirs["rec_model_dir"].endswith("ch_PP-OCRv4_rec_infer")
    assert dirs["cls_model_dir"].endswith("ch_ppocr_mobile_v2.0_cls_infer")


def test_bundled_ocr_model_dirs_returns_empty_without_bundle(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert ocr_converter._bundled_ocr_model_dirs() == {}


def test_ascii_ocr_model_root_copies_non_ascii_bundle(tmp_path, monkeypatch):
    source = tmp_path / "中文路径" / "whl"
    model_file = (
        source
        / "det"
        / "ch"
        / "ch_PP-OCRv4_det_infer"
        / "inference.pdmodel"
    )
    model_file.parent.mkdir(parents=True)
    model_file.write_text("model", encoding="utf-8")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))

    root = ocr_converter._ascii_ocr_model_root(source)

    assert "中文路径" not in str(root)
    assert (root / "det" / "ch" / "ch_PP-OCRv4_det_infer" / "inference.pdmodel").exists()


def test_image_to_markdown_uses_ocr_lines(tmp_path, monkeypatch):
    img = _write_image(tmp_path / "screen.png")
    monkeypatch.setattr(ocr_converter, "ocr_image", lambda image: ["第一行", "第二行"])

    result = image_to_markdown(img)

    assert "# screen" in result
    assert "<!-- ocr-source: screen.png -->" in result
    assert "第一行" in result
    assert "第二行" in result


def test_image_to_markdown_raises_when_ocr_unavailable(tmp_path, monkeypatch):
    img = _write_image(tmp_path / "screen.png")

    def fail(_image):
        raise OCRUnavailableError("missing ocr")

    monkeypatch.setattr(ocr_converter, "ocr_image", fail)

    with pytest.raises(OCRUnavailableError):
        image_to_markdown(img)


def test_enrich_markdown_images_inserts_local_ocr_block(tmp_path, monkeypatch):
    _write_image(tmp_path / "shot.png")
    monkeypatch.setattr(ocr_converter, "ocr_image", lambda image: ["alpha", "beta"])

    source = "before\n![shot](./shot.png)\nafter"
    result = enrich_markdown_images(source, tmp_path)

    assert "![shot](./shot.png)" in result
    assert "<!-- ocr -->" in result
    assert "> alpha" in result
    assert "> beta" in result
    assert "<!-- /ocr -->" in result


def test_enrich_markdown_images_skips_remote_and_data_images(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr_converter, "ocr_image", lambda image: calls.append(image))

    source = "![remote](https://example.com/a.png)\n![data](data:image/png;base64,abc)"
    result = enrich_markdown_images(source, tmp_path)

    assert result == source
    assert calls == []


def test_enrich_markdown_images_skips_missing_image(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr_converter, "ocr_image", lambda image: calls.append(image))

    source = "![missing](./missing.png)"
    result = enrich_markdown_images(source, tmp_path)

    assert result == source
    assert calls == []


def test_enrich_markdown_images_does_not_duplicate_existing_ocr(tmp_path, monkeypatch):
    _write_image(tmp_path / "shot.png")
    calls = []
    monkeypatch.setattr(ocr_converter, "ocr_image", lambda image: calls.append(image))

    source = "![shot](./shot.png)\n<!-- ocr -->\n> old\n<!-- /ocr -->"
    result = enrich_markdown_images(source, tmp_path)

    assert result == source
    assert calls == []
