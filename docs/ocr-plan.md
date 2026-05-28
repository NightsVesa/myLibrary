# Plan: OCR 图片导入 + PDF/DOCX/MD 嵌入图片识别

## Context

当前上传面板支持 `.docx`、`.pdf`、`.md`。存在三个文字丢失场景：
1. **独立图片文件**（截图、扫描件照片）无法导入
2. **PDF/DOCX 中的嵌入图片**被忽略 — PDF 扫描件 `extract_text()` 返回空，Word 中的截图文字丢失
3. **Markdown 中引用的本地图片** — `![desc](./img.png)` 引用的图片文字不进入知识库

目标：用 PaddleOCR 补全这三条路径，让所有图片中的文字都能进入知识库。

## 架构

```
converter/
├── ocr_converter.py     ← 新建：PaddleOCR 封装 + 独立图片转 Markdown
├── pdf_converter.py     ← 修改：嵌入图片 OCR + 扫描页整页 OCR
├── docx_converter.py    ← 修改：嵌入图片 OCR
ui/
├── upload_tab.py        ← 修改：SUPPORTED + filetypes + MD 图片 OCR
```

OCR 核心逻辑集中在 `ocr_converter.py`，其他模块调用它。PaddleOCR 延迟导入，未安装时优雅降级。

## Changes

### 1. 新建 `converter/ocr_converter.py`

**职责**：PaddleOCR 封装，提供统一的图片转文字接口。

```python
# 模块级单例，避免重复加载模型（首次 ~3-5s）
_ocr_instance = None

def _get_ocr():
    """延迟初始化 PaddleOCR，未安装时抛出清晰提示。"""

def ocr_image(img: Image.Image) -> list[str]:
    """对单张 PIL Image 执行 OCR，返回按行组织的文字列表。"""

def image_to_markdown(path: Path) -> str:
    """独立图片文件 → Markdown（供 SUPPORTED 字典使用）。"""
```

- 支持格式：`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.webp`
- `ocr_image` 接受 PIL.Image（方便 PDF/DOCX 模块复用，不需要先存文件）
- `image_to_markdown` 接受 Path（满足 converter 签名约定）
- 返回的文字按段落组织，非逐行换行

### 2. 修改 `converter/pdf_converter.py`

**改动**：在现有文字提取基础上，增加两层 OCR 兜底。

```python
def pdf_to_markdown(path: Path) -> str:
    # 原有逻辑：逐页 extract_text()
    # 新增：
    #   a) 每页 extract_text() 为空时 → pdfplumber page.to_image() 整页 OCR
    #   b) 每页 extract_text() 有内容时 → pypdf page.images 提取嵌入图片 → OCR
    #      将 OCR 结果追加到该页文字之后（标记为 <!-- ocr-image -->）
```

- **扫描页检测**：`page.extract_text()` 返回空或仅空白 → 整页渲染为图片 → OCR
- **嵌入图片**：用 `pypdf` 的 `page.images` 提取每张图片 → `ocr_image()` → 追加结果
- 两种情况都在现有 `<!-- page N -->` 标记内处理，输出格式不变
- PaddleOCR 未安装时：扫描页输出 `[此页为扫描件，需安装 paddleocr 以识别文字]`，嵌入图片跳过

### 3. 修改 `converter/docx_converter.py`

**改动**：遍历段落时，检测同段落或相邻段落的内联图片，提取并 OCR。

```python
def docx_to_markdown(path: Path) -> str:
    # 原有逻辑：遍历 doc.paragraphs 提取文字
    # 新增：在每个 paragraph 之后，检查该段关联的 inline_shapes
    #   → 提取图片 blob（via related_parts[rId].blob）
    #   → ocr_image() → 插入 OCR 结果
```

- 图片提取：`shape._inline.graphic.graphicData.pic.blipFill.blip.embed` → `doc.part.related_parts[rId].blob`
- 仅处理 `type == WD_INLINE_SHAPE.PICTURE` 的形状（跳过图表、SmartArt）
- OCR 结果以 `> [图片文字]` blockquote 格式插入，与正文区分
- PaddleOCR 未安装时：插入 `[图片文字需安装 paddleocr 以识别]`

### 4. 修改 `ui/upload_tab.py` 中的 `_md_passthrough`

**改动**：在读取 md 文件后，解析 `![...](...)` 图片引用，对本地图片 OCR 并插入文字。

```python
def _md_passthrough(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    # 新增：扫描 markdown 图片引用
    # 正则匹配 ![alt](path)，排除 http/https URL 和 data: URI
    # 对每个本地引用：
    #   1. 相对于 md 文件目录解析路径
    #   2. 文件存在 → ocr_image(Image.open(path)) → 获取文字
    #   3. 在图片引用行之后插入 OCR 结果（以 <!-- ocr --> 注释包裹）
    return text
```

- 正则：`!\[.*?\]\((?!https?://|data:)(.+?)\)` — 匹配本地路径引用
- 路径解析：`md_file_dir / match.group(1)`，处理 `./` 和 `../`
- OCR 结果格式：`<!-- ocr -->\n> 识别文字\n<!-- /ocr -->`，用注释包裹便于后续更新
- 图片不存在或 OCR 失败：跳过，不影响原文
- PaddleOCR 未安装：跳过，原文原样返回

### 5. 修改 `ui/upload_tab.py` UI 部分

- `SUPPORTED` 字典添加图片扩展名 → `image_to_markdown`
- `_pick_file` 的 `filetypes` 添加图片类型
- 行 0 提示文字更新

### 6. 更新 `CLAUDE.md`

- Required packages 添加 `paddleocr`、`paddlepaddle`（标记为 optional）

## 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `converter/ocr_converter.py` | **新建** | PaddleOCR 封装，`ocr_image()` + `image_to_markdown()` |
| `converter/pdf_converter.py` | 修改 | 扫描页整页 OCR + 嵌入图片 OCR |
| `converter/docx_converter.py` | 修改 | 嵌入图片 OCR |
| `ui/upload_tab.py` | 修改 | `_md_passthrough` 图片 OCR + SUPPORTED + filetypes |
| `CLAUDE.md` | 修改 | 依赖说明 |

## 依赖

- **新增**：`paddlepaddle` + `paddleocr`（pip install，~300MB）
- **已有，无需安装**：`pypdf`（v6.9.0）、`pdfplumber`（v0.11.9）、`python-docx`（v1.1.0）、`Pillow`（v12.2.0）

## 验证

```bash
pip install paddlepaddle paddleocr
python app.py
```

| 场景 | 预期 |
|------|------|
| 上传 `.png` 截图 | 预览显示 OCR 文字，保存后触发 ingest |
| 拖拽 `.jpg` 到宠物 | 保存到 notes/，触发 ingest |
| 上传扫描件 PDF（纯图片页） | 预览包含 OCR 文字（原来为空） |
| 上传含截图的 Word | 预览中图片文字以 blockquote 形式出现 |
| 上传引用本地图片的 .md | 预览中图片引用后附带 OCR 文字 |
| .md 引用的图片不存在 | 原文原样，无报错 |
| 未安装 paddleocr | 图片文件提示安装；PDF/DOCX/MD 退化为原行为 |
