# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for myLibrary
#
# Build:  pyinstaller build.spec
# Output: dist/myLibrary/

import sys
from pathlib import Path

block_cipher = None

# Locate tkinterdnd2 native libs for bundling
def _find_tkdnd():
    import tkinterdnd2
    base = Path(tkinterdnd2.__path__[0]) / "tkdnd"
    return str(base), "tkinterdnd2/tkdnd"

tkdnd_src, tkdnd_dst = _find_tkdnd()

datas = [
    ("assets", "assets"),           # pet sprite PNGs
    (tkdnd_src, tkdnd_dst),         # tkinterdnd2 native DLLs + tcl scripts
]

frontend_dist = Path("frontend") / "dist"
if frontend_dist.exists():
    datas.append((str(frontend_dist), "frontend"))

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
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
        "fastapi",
        "multipart",
        "multipart.multipart",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "webview",
        "webview.platforms",
        "webview.platforms.edgechromium",
        "pythonnet",
        "clr_loader",
        "proxy_tools",
        "bottle",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio",
        "paddle", "paddleocr", "paddlepaddle",
        "numpy", "scipy", "pandas",
        "matplotlib", "plotly", "seaborn",
        "sklearn", "skimage",
        "cv2", "opencv",
        "astropy", "pyerfa",
        "IPython", "jupyter", "notebook", "ipykernel",
        "qtpy", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "sphinx", "sphinxcontrib",
        "pytest", "coverage",
        "tensorboard", "tensorflow",
        "transformers", "datasets",
        "sympy", "networkx",
        "boto3", "botocore", "s3transfer",
        "flask", "django",
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
    name="myLibrary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # no console window
    icon="assets/app_icon.ico",
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
    name="myLibrary",
)
