# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 知识库助手
#
# Build:  pyinstaller build.spec
# Output: dist/知识库助手/

import sys
from pathlib import Path

block_cipher = None

# Locate tkinterdnd2 native libs for bundling
def _find_tkdnd():
    import tkinterdnd2
    base = Path(tkinterdnd2.__path__[0]) / "tkdnd"
    return str(base), "tkinterdnd2/tkdnd"

tkdnd_src, tkdnd_dst = _find_tkdnd()

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets", "assets"),           # pet sprite PNGs
        (tkdnd_src, tkdnd_dst),         # tkinterdnd2 native DLLs + tcl scripts
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio",
        "numpy", "scipy", "pandas",
        "matplotlib", "plotly", "seaborn",
        "sklearn", "skimage",
        "cv2", "opencv",
        "astropy", "pyerfa",
        "IPython", "jupyter", "notebook", "ipykernel",
        "sphinx", "sphinxcontrib",
        "pytest", "coverage",
        "tensorboard", "tensorflow",
        "transformers", "datasets",
        "sympy", "networkx",
        "boto3", "botocore", "s3transfer",
        "flask", "django", "fastapi", "uvicorn",
        "sqlalchemy", "alembic",
        "requests",
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
    name="知识库助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # no console window
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
    name="知识库助手",
)
