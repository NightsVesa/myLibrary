# 知识库助手

[English](README.en.md) | 简体中文

Windows 桌面宠物知识库应用。它把一只悬浮在桌面的三角龙变成知识库入口：悬停显示侧边栏，打开输入、上传、搜索、问答、图谱和体检面板，用本地 Markdown、自动生成 wiki 和 LLM 问答一起维护个人知识库。

## 宠物预览

项目实际使用的宠物精灵图位于 `assets/`，运行时通过 Windows 透明色 `#ff00ff` 抠掉背景。下面是同一批精灵导出的白底预览图，避免 README 里出现透明色背景。

<p>
  <img src="assets/readme_pet_idle.png" width="150" alt="idle pet">
  <img src="assets/readme_pet_happy.png" width="150" alt="happy pet">
  <img src="assets/readme_pet_eat.png" width="150" alt="eat pet">
  <img src="assets/readme_pet_attack.png" width="150" alt="attack pet">
  <img src="assets/readme_pet_sleep.png" width="150" alt="sleep pet">
</p>

| 状态 | 白底预览 |
| --- | --- |
| 待机 | <img src="assets/readme_pet_idle.png" width="120" alt="idle frame"> |
| 开心 | <img src="assets/readme_pet_happy.png" width="120" alt="happy frame"> |
| 进食 | <img src="assets/readme_pet_eat.png" width="120" alt="eat frame"> |
| 攻击/拖拽 | <img src="assets/readme_pet_attack.png" width="120" alt="attack frame"> |
| 睡觉 | <img src="assets/readme_pet_sleep.png" width="120" alt="sleep frame"> |

## 功能

- 桌面宠物入口：置顶、透明背景、可拖拽，支持休眠和点击动画。
- 快速记录：把文本保存为 `notes/` 下的 Markdown 笔记。
- 文件导入：支持 `.md`、`.docx`、`.pdf` 和常见图片格式，上传或拖放到宠物上都会走同一套保存流程。
- 可选 OCR：安装 PaddleOCR 后，图片、扫描页和文档内截图中的文字可进入 Markdown / wiki。
- 本地搜索：对 `notes/` 下的 Markdown 做全文搜索，支持标签、收藏、最近打开和阅读器预览。
- LLM wiki：把原始笔记编译成 `wiki/` 下的 sources、entities、concepts、index 和 log。
- 问答面板：基于 wiki 检索上下文并流式回答。
- 知识图谱：展示 wiki 页面之间的关联，支持筛选、路径查找和质量信号。
- Wiki 体检：检查孤立页、断链、索引漂移、重复项和潜在维护问题。

## 安装

本项目面向 Windows 桌面运行，推荐 Python 3.10+。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

依赖清单主文件为 `requirements.txt`，同时提供 `requirement.txt` 作为同内容兼容文件。

可选 OCR 支持较大，默认不放进基础安装：

```bash
pip install paddleocr paddlepaddle
```

`reportlab` 只用于一个 PDF 测试；没有安装时相关测试会跳过。

## LLM 配置

复制模板并填写本地密钥：

```bash
copy .env.template .env
```

示例：

```env
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
```

任何 OpenAI-compatible endpoint 都可以使用，例如 DeepSeek、SenseNova、Ollama、Groq、LM Studio。没有配置 `LLM_API_KEY` 时，wiki ingest 和问答等 LLM 功能会静默跳过，其余本地功能仍可使用。

## 常用命令

```bash
# 启动应用
python app.py

# 运行全部测试
python -m pytest tests/

# 运行单个测试文件或测试
python -m pytest tests/test_wiki_engine.py -v
python -m pytest tests/test_grep_search.py::test_case_insensitive -v

# 打包轻量 Windows exe，输出到 dist/myLibrary/
pyinstaller build.spec --noconfirm

# 打包 OCR Windows exe，输出到 dist/myLibrary-OCR/
pyinstaller build_ocr.spec --noconfirm
```

## Release 2.0

Release 2.0 提供两个 Windows one-folder zip 附件：

| 附件 | OCR | 适合 |
| --- | --- | --- |
| `myLibrary-release2.0-lite-windows.zip` | 不包含 | 只需要记录、搜索、wiki、问答和图谱，优先小体积 |
| `myLibrary-release2.0-ocr-windows.zip` | 包含 PaddleOCR、PaddlePaddle 和中文 OCR 模型 | 需要图片、扫描 PDF、文档内图片识别 |

解压后运行：

```text
myLibrary/myLibrary.exe
myLibrary-OCR/myLibrary-OCR.exe
```

打包版行为：

- `assets/` 被打进 `_internal`，包含本项目实际使用的宠物帧。
- `notes/`、`wiki/`、`.env` 位于 exe 同级目录，方便用户写入和迁移。
- 轻量包不打包 PaddleOCR / paddlepaddle；OCR 包内置中文检测、识别和方向分类模型，用户不需要再手动安装 OCR 依赖。
- OCR 包首次识别时如果发现模型路径包含非 ASCII 字符，会自动复制模型到 `C:\ProgramData\myLibrary\paddleocr\` 等 ASCII 缓存目录，避免 Paddle 在中文路径下打不开模型文件。

## 目录结构

```text
assets/       宠物精灵图和 UI 资源
converter/    docx/pdf/markdown/OCR 转换
llm/          LLM client、wiki engine、prompt、lint、graph 数据
notes/        原始用户笔记，本地可写，默认不提交
search/       本地全文搜索
storage/      笔记保存和轻量元数据
tests/        pytest 测试
ui/           Tkinter 面板、控件、搜索阅读器、聊天和图谱 UI
wiki/         LLM 维护的 wiki 输出，本地可写，默认不提交
```

## Wiki 工作流

知识库分为三层：

- `notes/`：原始资料，作为 source of truth。
- `notes/.note_meta.json`：本地整理元数据，保存标签、收藏和最近打开记录，不写入 Markdown 正文。
- `wiki/`：LLM 维护的编译层，包含 source summaries、entity pages、concept pages、`index.md` 和 `log.md`。
- schema/prompt：`AGENTS.md` 和 `llm/prompts.py` 约束 LLM 如何写入、查询和维护 wiki。

查询时会优先读取 `wiki/index.md` 找候选页面，再读取候选 wiki 页和一跳 `## Related` 页面。默认不读取 `notes/` 原文；只有用户明确要求“原文”“raw”“核对原文”“逐字”“第几页”等核查场景时，才读取少量匹配原文作为辅助证据。

## 开发备注

- UI 采用多个透明 `Toplevel` 层：宠物、侧边栏、面板、阅读器。
- 面板主题来自 `ui/main_window.py` 的 `ACTIONS`。
- 动画集中在 `MainWindow._tick()`，不要为单个状态新增独立 `after()` 循环。
- 上传支持格式集中在 `ui/upload_tab.py` 的 `SUPPORTED`，实际保存路径由 `save_supported_upload()` 统一处理。
- 笔记标签、收藏和最近打开记录由 `storage/note_meta.py` 管理，搜索框输入 `#标签` 可按标签筛选。
- 手写 Markdown renderer 在 `ui/markdown_render.py`，避免引入额外 markdown 依赖。
