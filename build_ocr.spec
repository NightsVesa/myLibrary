# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 知识库助手 OCR release
#
# Build:  pyinstaller build_ocr.spec
# Output: dist/知识库助手-OCR/

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

block_cipher = None


def _find_tkdnd():
    import tkinterdnd2

    base = Path(tkinterdnd2.__path__[0]) / "tkdnd"
    return str(base), "tkinterdnd2/tkdnd"


def _ocr_model_data():
    root = Path.home() / ".paddleocr" / "whl"
    if not root.exists():
        return []
    return [(str(root), ".paddleocr/whl")]


tkdnd_src, tkdnd_dst = _find_tkdnd()

ocr_datas = (
    collect_data_files("paddle", include_py_files=False)
    + collect_data_files("paddleocr", include_py_files=False)
    + collect_data_files("cv2", include_py_files=False)
    + copy_metadata("paddleocr")
    + copy_metadata("paddlepaddle")
)
ocr_binaries = collect_dynamic_libs("paddle") + collect_dynamic_libs("cv2")
ocr_hiddenimports = [
    "paddle",
    "paddleocr",
    "cv2",
    "numpy",
    *collect_submodules("paddleocr.tools.infer"),
    *collect_submodules("paddleocr.ppocr.postprocess"),
    *collect_submodules("paddleocr.ppocr.utils"),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=ocr_binaries,
    datas=[
        ("assets", "assets"),
        (tkdnd_src, tkdnd_dst),
        *_ocr_model_data(),
        *ocr_datas,
    ],
    hiddenimports=[
        "ttkbootstrap",
        "ttkbootstrap.themes",
        "ttkbootstrap.themes.standard",
        "tkinterdnd2",
        "PIL",
        "PIL._tkinter_finder",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "httpcore",
        "httpcore._sync",
        "httpcore._async",
        "certifi",
        "h11",
        "dotenv",
        "pdfplumber",
        "docx",
        *ocr_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio",
        "scipy", "pandas",
        "matplotlib", "plotly", "seaborn",
        "panel", "bokeh", "pyarrow", "llvmlite", "numba",
        "tensorflow", "tensorboard", "transformers", "datasets",
        "sklearn", "skimage",
        "astropy", "pyerfa",
        "IPython", "jupyter", "notebook", "ipykernel",
        "sphinx", "sphinxcontrib",
        "pytest", "coverage",
        "sympy", "networkx",
        "boto3", "botocore", "s3transfer",
        "flask", "django", "fastapi", "uvicorn",
        "sqlalchemy", "alembic",
        "setuptools", "wheel", "pip",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="知识库助手-OCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="知识库助手-OCR",
)
