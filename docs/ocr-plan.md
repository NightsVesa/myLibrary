# Plan: OCR 图片导入 + 文档内图片识别

## Goal

让图片中的文字真正进入知识库，而不只是出现在上传预览里。

需要覆盖三条路径：

1. 独立图片文件：截图、扫描件照片、图片笔记。
2. PDF / DOCX 内嵌图片：扫描页、截图、图片型表格。
3. Markdown 本地图片引用：`![desc](./image.png)` 指向的图片。

验收标准：

- 上传或拖拽图片后，`notes/` 中保存的是 OCR 后的 `.md`，全文搜索能搜到图片文字。
- 上传或拖拽 PDF / DOCX 后，wiki ingest 能读到普通文本和 OCR 文本。
- 上传或拖拽 Markdown 后，本地图片 OCR 文本会随 Markdown 一起进入 wiki。
- 未安装 OCR 依赖时，现有 DOCX / PDF / MD 行为不被破坏。

## Current Constraints

当前上传链路不是“转换后保存 Markdown”，而是复制原文件：

- `ui/upload_tab.py:_update_preview()` 会调用 `SUPPORTED` 中的 converter 生成预览。
- `ui/upload_tab.py:_on_save()` 调用 `save_raw_file()`，保存的是原始文件。
- `ui/main_window.py:_on_files_dropped()` 也调用 `save_raw_file()`，拖拽同样保存原始文件。
- `llm/wiki_engine.py:_read_note_source()` 目前只支持 `.md`、`.docx`、`.pdf`。

因此，独立图片不能只添加到 `SUPPORTED`。如果保存到 `notes/` 的仍是 `.png` / `.jpg`，全文搜索不会命中，wiki ingest 也会因为不支持图片扩展名失败。

## First Release Decisions

第一版先做稳定闭环，不改整个存储模型：

- 独立图片上传 / 拖拽：OCR 成功后保存为 `.md`，因此可被全文搜索和 wiki ingest 命中。
- Markdown 文件：保存时写入增强后的 Markdown，因此本地图片 OCR 文本可被全文搜索和 wiki ingest 命中。
- PDF / DOCX：仍保存原文件；OCR 文本进入转换结果和 wiki ingest，但不承诺被现有全文搜索命中。
- OCR 缺失：独立图片不保存占位笔记，只在 UI 提示安装 `paddleocr` / `paddlepaddle`；PDF / DOCX / MD 内部图片跳过 OCR，不影响原文字导入。
- UI 性能：OCR 预览和 OCR 保存不能长期阻塞 Tk 主线程；入口层使用后台线程，结果通过 `root.after()` 回填。
- 打包策略：第一版 OCR 作为源码运行的可选能力，默认 PyInstaller 包不内置 PaddleOCR / paddlepaddle；如需 OCR 版安装包，后续单独做 build profile。

## Architecture

```
converter/
├── ocr_converter.py      # 新建：OCR 封装、图片转 Markdown、MD 图片引用增强
├── pdf_converter.py      # 修改：扫描页整页 OCR；必要时处理嵌入图片
├── docx_converter.py     # 修改：按段落 run 顺序提取图片并 OCR
storage/
├── note_store.py         # 可选修改：增加 save_converted_file()
ui/
├── upload_tab.py         # 修改：预览、保存、SUPPORTED、filetypes
├── main_window.py        # 修改：拖拽图片时保存转换后的 Markdown
llm/
├── wiki_engine.py        # 修改：识别图片扩展名或统一依赖 converter 读取源文件
```

核心原则：

- OCR 逻辑集中在 `converter/ocr_converter.py`。
- PaddleOCR 延迟导入，避免启动应用时加载模型；单例初始化需要加线程锁。
- 独立图片最终保存为 Markdown，不把图片原样塞进 `notes/` 后交给 wiki 猜。
- PDF / DOCX 仍可保存原文件，因为 `_read_note_source()` 会在 ingest 时转换。
- Markdown 保存增强后的 Markdown，让本地图片 OCR 文本也能被全文搜索命中。

## Implementation Plan

### 1. 新建 `converter/ocr_converter.py`

职责：提供统一 OCR 接口和图片 Markdown 转换。

建议 API：

```python
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

class OCRUnavailableError(RuntimeError):
    """Raised when PaddleOCR is not installed or cannot be initialized."""

def is_image_file(path: Path) -> bool:
    """Return True for supported local image suffixes."""

def ocr_image(img: Image.Image) -> list[str]:
    """Run OCR on one PIL image and return recognized text lines."""

def image_to_markdown(path: Path) -> str:
    """Convert an image file to Markdown containing OCR text."""

def enrich_markdown_images(source: str, base_dir: Path) -> str:
    """Insert OCR text after local Markdown image references."""
```

输出约定：

- `image_to_markdown()` 输出一个 Markdown 文件体，例如：

```markdown
# image-name

<!-- ocr-source: image-name.png -->

识别出的文字段落
```

- `enrich_markdown_images()` 在本地图片引用后插入：

```markdown
<!-- ocr -->
> 识别文字
<!-- /ocr -->
```

降级约定：

- `ocr_image()` 在 PaddleOCR 缺失时抛 `OCRUnavailableError`。
- 独立图片预览可以显示清晰提示：

```markdown
[图片文字需安装 paddleocr 和 paddlepaddle 后识别]
```

- 独立图片保存时遇到 `OCRUnavailableError` 应阻止保存，避免把安装提示写进知识库。
- PDF / DOCX / MD 内部图片在 OCR 不可用时跳过或插入简短提示，但不能让原文转换失败。

### 2. 修正上传保存链路

`ui/upload_tab.py` 需要区分两类文件：

- 原始文件保存：`.docx`、`.pdf`。
- 转换后 Markdown 保存：图片文件。
- 增强后 Markdown 保存：`.md`。

建议做法：

```python
if is_image_file(self._selected):
    md = image_to_markdown(self._selected)
    path = save_note(md, title=self._selected.stem)
elif self._selected.suffix.lower() == ".md":
    md = _md_passthrough(self._selected)
    path = save_note(md, title=self._selected.stem)
else:
    path = save_raw_file(self._selected)
```

这样上传图片和引用本地图片的 Markdown 后，`notes/` 中得到的是含 OCR 文本的 `.md`，全文搜索和 wiki ingest 都能直接处理。

`ui/main_window.py:_on_files_dropped()` 同样要处理图片：

- 图片：`image_to_markdown()` -> `save_note()` -> `_ingest_with_animation([saved_md])`
- Markdown：`_md_passthrough()` -> `save_note()` -> `_ingest_with_animation([saved_md])`
- DOCX / PDF：沿用 `save_raw_file()`

注意：拖拽和上传必须共享同一套保存判断，避免一个能入库、另一个只能预览。

### 3. 修改 Markdown passthrough

`ui/upload_tab.py:_md_passthrough()` 不应只原样读取，应调用 `enrich_markdown_images()`：

```python
def _md_passthrough(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return enrich_markdown_images(text, Path(path).parent)
```

需要处理：

- 排除 `http://`、`https://`、`data:` 图片。
- 支持相对路径：`./img.png`、`../assets/img.png`。
- 跳过不存在的文件。
- 跳过已经有 `<!-- ocr --> ... <!-- /ocr -->` 的图片块，避免重复插入。
- 支持包含空格的 Markdown 链接路径，至少覆盖常见未转义路径。

wiki ingest 的 `_read_note_source()` 对 `.md` 也应复用同样逻辑，保证拖拽保存后的 Markdown 在 ingest 时能得到图片 OCR 文本。

### 4. 修改 `llm/wiki_engine.py:_read_note_source()`

两种可选实现，推荐第一种：

1. 推荐：对图片扩展名直接转换为 Markdown。

```python
if is_image_file(path):
    from converter.ocr_converter import image_to_markdown
    return image_to_markdown(path)
```

同时 `.md` 分支调用 `enrich_markdown_images()`。

2. 备选：强制所有图片上传/拖拽都先保存成 `.md`，`_read_note_source()` 不支持图片。

第一种更稳，因为即使用户手动把图片放进 `notes/`，wiki ingest 仍能处理。

### 5. 修改 `converter/pdf_converter.py`

先实现扫描页整页 OCR，嵌入图片 OCR 作为第二阶段。

阶段 1：扫描页整页 OCR

- 继续逐页调用 `page.extract_text()`。
- 如果有文字：保持现有输出。
- 如果无文字：用 `pdfplumber` 渲染该页为图片后 OCR。
- OCR 结果仍放在 `<!-- page N -->` 标记内。

示意：

```python
if text.strip():
    pages.append(f"<!-- page {i} -->\n{text.strip()}")
else:
    img = page.to_image(resolution=200).original
    lines = ocr_image(img)
    if lines:
        pages.append(f"<!-- page {i} -->\n<!-- ocr-page -->\n{body}")
```

注意事项：

- `page.to_image()` 在某些环境可能依赖 ImageMagick/Ghostscript 或 PDF 渲染能力；实现前先用本机环境验证。
- 如果 OCR 不可用，建议保持当前行为：空扫描页不输出，或只在预览层提示。不要让普通 PDF 转换失败。
- 不建议第一版引入 `pypdf page.images`，除非先确认项目依赖中确实已有 `pypdf`。若要实现嵌入图片 OCR，应把 `pypdf` 标成新增可选依赖，并加测试。

阶段 2：嵌入图片 OCR

- 只有在普通文本 PDF 中确实有图片文字丢失需求时再加。
- 新增依赖必须写入 `AGENTS.md` / `CLAUDE.md`。
- OCR 结果追加在该页正文之后：

```markdown
<!-- ocr-image -->
> 图片文字
```

### 6. 修改 `converter/docx_converter.py`

目标：保持正文顺序，并在图片出现的位置附近插入 OCR 结果。

不要只遍历 `doc.inline_shapes` 后统一追加；那会丢失顺序。建议遍历 paragraph 的 runs，检查每个 run 的 XML 是否包含图片 blip：

```python
for para in doc.paragraphs:
    # 先按现有逻辑输出 para.text / heading
    # 再遍历 para.runs，查找 a:blip 的 r:embed
    # 通过 doc.part.related_parts[r_id].blob 读取图片
```

OCR 输出格式：

```markdown
> [图片文字] 识别文字
```

注意事项：

- 仅处理图片关系，跳过图表、SmartArt、公式等非图片对象。
- 同一图片关系可能被多个 run 引用，要避免重复 OCR。
- OCR 失败不应影响 DOCX 正文转换。

### 7. 更新 UI 支持格式

`ui/upload_tab.py`：

- `SUPPORTED` 增加图片扩展名到 `image_to_markdown`。
- 文件选择器增加图片类型。
- 标题从“选择 DOCX / PDF / Markdown 文件”改为“选择 DOCX / PDF / Markdown / 图片文件”。
- 预览继续调用 converter，因此图片会显示 OCR Markdown。

### 8. 更新文档和依赖说明

更新 `AGENTS.md` 和 `CLAUDE.md`：

- `paddleocr`、`paddlepaddle` 标为 optional，不放进必需依赖。
- 如果实现 PDF 嵌入图片 OCR 并使用 `pypdf`，把 `pypdf` 标为 optional。
- 说明图片上传会保存为 OCR 后的 Markdown。
- 说明未安装 OCR 依赖时，独立图片只在 UI 提示安装依赖且不保存占位笔记，DOCX / PDF / MD 原有文本路径仍可用。

## Tests

不要求测试真实 PaddleOCR。用 monkeypatch/mock 覆盖主流程。

新增测试建议：

| 测试 | 目标 |
|------|------|
| `test_image_to_markdown_uses_ocr_lines` | 图片转换生成 Markdown，包含 OCR 文字 |
| `test_image_to_markdown_unavailable_raises` | OCR 缺失时独立图片不生成占位笔记 |
| `test_md_passthrough_enriches_local_image` | Markdown 本地图片后插入 OCR block |
| `test_md_passthrough_skips_remote_image` | 远程 URL 和 data URI 不处理 |
| `test_md_passthrough_skips_missing_image` | 图片不存在时原文保留 |
| `test_pdf_scanned_page_uses_ocr_when_no_text` | PDF 空文本页触发 OCR |
| `test_pdf_text_page_keeps_existing_behavior` | 普通 PDF 不受影响 |
| `test_docx_image_run_inserts_ocr_text` | DOCX 图片 run 后插入 blockquote |
| `test_read_note_source_supports_image` | wiki ingest 读取图片源得到 Markdown |

现有测试也要跑：

```bash
python -m pytest tests/test_pdf_converter.py tests/test_docx_converter.py -v
python -m pytest tests/ -v
```

## Manual Verification

安装可选 OCR 依赖后验证：

```bash
pip install paddlepaddle paddleocr
python app.py
```

场景：

| 场景 | 预期 |
|------|------|
| 上传 `.png` 截图 | 预览显示 OCR 文本；保存后 `notes/` 出现 `.md` |
| 拖拽 `.jpg` 到宠物 | 保存 `.md`；wiki ingest 不报 unsupported suffix |
| 搜索图片中的文字 | 搜索结果命中对应 `.md` |
| 上传扫描件 PDF | OCR 文本进入预览和 wiki |
| 上传含截图的 DOCX | 图片文字以 blockquote 进入 Markdown |
| 上传引用本地图片的 `.md` | 图片引用后插入 OCR block |
| OCR 依赖未安装 | DOCX / PDF / MD 普通文本仍可导入；图片显示清晰提示 |

## Rollout Order

1. 实现 `ocr_converter.py` 和 mock 测试。
2. 修正上传/拖拽图片保存为 Markdown。
3. 让 `_read_note_source()` 支持图片和 Markdown 图片增强。
4. 实现 PDF 扫描页 OCR。
5. 实现 DOCX run 图片 OCR。
6. 视需求再实现 PDF 嵌入图片 OCR。
7. 更新 `AGENTS.md` / `CLAUDE.md` 和手工验证。

## Execution Plan

### Phase 0: Baseline Check

目标：确认当前行为和测试基线，避免 OCR 改动掩盖已有问题。

操作：

1. 运行现有转换器测试：

```bash
python -m pytest tests/test_pdf_converter.py tests/test_docx_converter.py -v
```

2. 运行上传相关的轻量测试，如果没有专门测试，先只记录缺口。
3. 确认 `notes/`、`wiki/` 中已有文件不需要迁移。

验收：

- 现有 PDF / DOCX 转换器测试通过，或记录明确的既有失败。
- 明确本次实现不改动旧笔记文件。

### Phase 1: OCR Core Module

目标：新建可 mock、可降级的 OCR 核心模块。

改动文件：

- `converter/ocr_converter.py`
- `tests/test_ocr_converter.py`

实现步骤：

1. 定义 `IMAGE_SUFFIXES`、`OCRUnavailableError`、`is_image_file()`。
2. 实现 `_get_ocr()` 模块级单例，延迟导入 `paddleocr.PaddleOCR`。
3. 实现 `ocr_image(img)`：
   - 接收 `PIL.Image.Image`。
   - 转为 PaddleOCR 可识别的数据格式。
   - 兼容 PaddleOCR 常见返回结构。
   - 返回去空白后的 `list[str]`。
4. 实现 `_format_ocr_lines(lines)`，把多行结果压成适合 Markdown 的段落。
5. 实现 `image_to_markdown(path)`：
   - 校验文件存在。
   - 使用 Pillow 打开图片并 OCR。
   - OCR 不可用时返回安装提示 Markdown。
   - OCR 为空时返回空识别提示。
6. 实现 `enrich_markdown_images(source, base_dir)`：
   - 识别本地 Markdown 图片引用。
   - 跳过远程 URL、`data:`、不存在文件、非图片后缀。
   - 图片后已有 `<!-- ocr -->` 块时跳过。
   - OCR 失败时不改变原图片引用。

测试：

```bash
python -m pytest tests/test_ocr_converter.py -v
```

验收：

- 不安装 PaddleOCR 时，导入 `converter.ocr_converter` 不失败。
- mock `ocr_image()` 后，图片和 Markdown 图片增强能稳定生成预期 Markdown。

### Phase 2: Upload Save Path

目标：上传独立图片和 Markdown 后，保存到 `notes/` 的是可搜索的 `.md`。

改动文件：

- `ui/upload_tab.py`
- `ui/main_window.py`
- 可能新增：`storage/note_store.py`
- `tests/test_upload_ocr_save.py` 或相近测试文件

实现步骤：

1. 在 `ui/upload_tab.py` 中导入：
   - `image_to_markdown`
   - `is_image_file`
   - `IMAGE_SUFFIXES`
   - `save_note`
2. 扩展 `SUPPORTED`：
   - 图片后缀映射到 `image_to_markdown`。
3. 更新文件选择器：
   - “支持的文件”包含 `.docx .pdf .md` 和图片扩展名。
   - 新增“图片”类型。
4. 修改 `_on_save()`：
   - 图片：`image_to_markdown()` -> `save_note(md, title=stem)`。
   - Markdown：`_md_passthrough()` -> `save_note(md, title=stem)`。
   - DOCX / PDF：沿用 `save_raw_file()`。
5. 修改 `ui/main_window.py:_on_files_dropped()`：
   - 图片：转换后 `save_note()`。
   - Markdown：增强后 `save_note()`。
   - DOCX / PDF：沿用 `save_raw_file()`。
6. 如上传和拖拽出现重复逻辑，抽一个很小的 helper；只在能明显减少重复时添加。
7. OCR 预览和 OCR 保存通过后台线程执行，完成后用 `root.after()` 更新 UI。
8. 独立图片 OCR 不可用时阻止保存并提示安装依赖；Markdown 内部图片 OCR 不可用时保留原文。

测试：

- mock `image_to_markdown()` 返回固定 Markdown。
- mock `_md_passthrough()` 返回增强 Markdown。
- mock 或使用临时 `notes_dir` 验证图片保存为 `.md`。
- 验证 Markdown 保存为增强后的 `.md`。
- 验证 DOCX / PDF 仍调用原始保存路径。

验收：

- 上传图片后，`notes/xxx.md` 存在。
- 上传引用本地图片的 Markdown 后，`notes/xxx.md` 包含 OCR block。
- 拖拽图片后，传给 `_ingest_with_animation()` 的路径是 `.md`。
- 搜索层能通过现有 Markdown 搜索命中图片和 Markdown 图片 OCR 文本。

### Phase 3: Wiki Source Reading

目标：wiki ingest 对图片和 Markdown 本地图片引用都可读。

改动文件：

- `llm/wiki_engine.py`
- `tests/test_wiki_engine_ocr_source.py` 或现有 wiki 测试文件

实现步骤：

1. 修改 `_read_note_source(path)`：
   - `.md`：读取文本后调用 `enrich_markdown_images(text, path.parent)`。
   - 图片：调用 `image_to_markdown(path)`。
   - `.docx` / `.pdf`：保持现有分支。
2. 保持未知扩展名仍抛 `ValueError`。
3. 避免在模块顶层导入 OCR，所有 OCR 相关导入放在分支内部。

测试：

- mock `enrich_markdown_images()`，验证 `.md` 分支调用。
- mock `image_to_markdown()`，验证图片分支调用。
- 验证未知扩展名仍报错。

验收：

- 即使用户手动把图片放入 `notes/`，wiki ingest 也能读取为 Markdown。
- 未安装 PaddleOCR 时，wiki ingest 不会因为导入 OCR 模块失败而中断普通 `.md/.docx/.pdf`。

### Phase 4: PDF Scanned Page OCR

目标：PDF 文本页保持原行为，扫描页可通过整页 OCR 进入 Markdown。

改动文件：

- `converter/pdf_converter.py`
- `tests/test_pdf_converter.py`

实现步骤：

1. 在 `pdf_to_markdown()` 内保留现有 `extract_text()` 流程。
2. 当 `extract_text()` 为空或仅空白时：
   - 调用 `page.to_image(resolution=200).original` 获取 PIL image。
   - 调用 `ocr_image(img)`。
   - 有 OCR 结果时追加：

```markdown
<!-- page N -->
<!-- ocr-page -->
OCR 文本
```

3. 捕获 `OCRUnavailableError`，保持当前空页省略行为。
4. 捕获页面渲染失败，跳过该页 OCR，不影响其他页。
5. 暂不实现 `pypdf page.images`。

测试：

- mock 一个空文本 page，验证触发 `ocr_image()`。
- mock 一个有文本 page，验证不触发 OCR，输出保持原格式。
- mock `OCRUnavailableError`，验证不抛出。

验收：

- 普通 PDF 测试继续通过。
- 扫描页在 OCR 可用时输出 OCR 文本。
- OCR 不可用时 PDF 转换不失败。

### Phase 5: DOCX Image OCR

目标：DOCX 中图片文字按所在段落附近进入 Markdown。

改动文件：

- `converter/docx_converter.py`
- `tests/test_docx_converter.py`

实现步骤：

1. 保留现有 heading / paragraph 转换逻辑。
2. 对每个 paragraph 的 runs 检查 XML 中的 `a:blip`；即使 `para.text` 为空也要检查，避免漏掉图片单独占一段的情况。
3. 读取 `r:embed` 对应的 `doc.part.related_parts[r_id].blob`。
4. 用 `PIL.Image.open(BytesIO(blob))` 转成图片。
5. 调用 `ocr_image(img)`。
6. 在该段落之后插入：

```markdown
> [图片文字] OCR 文本
```

7. 用 `seen_rids` 避免同一图片重复识别。
8. 捕获 OCR 不可用和单图失败，正文转换继续。

测试：

- 构造带内嵌图片的 DOCX，mock OCR 返回固定文字。
- 验证正文、标题、图片 OCR 文本都存在。
- 验证 OCR 不可用时正文仍正常输出。

验收：

- 现有 DOCX 测试继续通过。
- 图片 OCR 结果出现在图片所在段落附近，而不是统一追加到文末。

### Phase 6: Documentation

目标：让项目说明和实际行为一致。

改动文件：

- `AGENTS.md`
- `CLAUDE.md`
- 可选：`README.md`

更新内容：

1. Required packages 保持不变。
2. Optional packages 增加：
   - `paddleocr`
   - `paddlepaddle`
3. 上传说明增加：
   - 图片文件会 OCR 后保存为 Markdown。
   - DOCX / PDF / MD 内部图片会尽量 OCR。
   - 未安装 OCR 依赖时普通文本导入不受影响。
4. 如果未来实现 PDF 嵌入图片 OCR 并引入 `pypdf`，再把 `pypdf` 写入 optional。

验收：

- 文档没有声称 `pypdf` 已是现有依赖。
- AGENTS 和 CLAUDE 中关于上传格式、OCR 降级的说明一致。

### Phase 7: Full Verification

目标：确认单元测试、关键手工流程和降级路径都成立。

自动测试：

```bash
python -m pytest tests/test_ocr_converter.py -v
python -m pytest tests/test_pdf_converter.py tests/test_docx_converter.py -v
python -m pytest tests/ -v
```

无 OCR 依赖手工验证：

1. 启动应用。
2. 上传普通 `.md`、`.docx`、`.pdf`。
3. 上传图片，确认出现安装提示 Markdown，而不是崩溃。

有 OCR 依赖手工验证：

1. 安装：

```bash
pip install paddlepaddle paddleocr
```

2. 启动：

```bash
python app.py
```

3. 验证：
   - 上传截图，`notes/` 保存 `.md`。
   - 搜索截图中的文字。
   - 拖拽图片到宠物，ingest 不报扩展名错误。
   - 上传扫描 PDF，预览含 OCR 文本。
   - 上传含截图 DOCX，预览含 blockquote OCR 文本。
   - 上传引用本地图片的 Markdown，预览和 wiki 读取都含 OCR block。

最终验收：

- 独立图片和 Markdown 本地图片 OCR 文本能进入 `notes/`、全文搜索、wiki ingest 三个链路。
- PDF / DOCX OCR 文本能进入转换结果和 wiki ingest；第一版不承诺被全文搜索命中。
- OCR 缺失时，普通文档导入仍按原行为工作。
- 没有新增启动时重依赖加载。
- 没有把 PDF 嵌入图片 OCR 和 `pypdf` 作为第一版硬依赖。
