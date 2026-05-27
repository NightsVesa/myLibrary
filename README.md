# 知识库助手

一个 Windows 桌面宠物知识库应用。它把一只悬浮在桌面的三角龙变成知识库入口：悬停显示侧边栏，打开输入、上传、搜索、问答、图谱和体检面板，用本地 Markdown、自动生成 wiki 和 LLM 问答一起维护个人知识库。

## 功能

- 桌面宠物入口：置顶、透明背景、可拖拽，支持休眠和点击动画。
- 快速记录：把文本保存为 `notes/` 下的 Markdown 笔记。
- 文件导入：支持 `.md`、`.docx`、`.pdf`，上传或拖放到宠物上都会走同一套转换流程。
- 本地搜索：对 `notes/` 下的 Markdown 做全文搜索，并支持阅读器预览。
- LLM wiki：把原始笔记编译成 `wiki/` 下的 sources、entities、concepts、synthesis 页面。
- 问答面板：基于 `index.md` 优先召回 wiki 页面，读取相关页面后流式回答，并可把高价值回答保存成 synthesis 页面。
- 知识图谱：展示 wiki 页面之间的关联。
- Wiki 体检：检查孤立页、断链、索引漂移、重复项和潜在维护问题。

## 运行环境

本项目面向 Windows 桌面运行，依赖 Tk 的透明色能力：

```bash
python app.py
```

推荐 Python 3.10+。项目没有固定的 `requirements.txt`，需要按需安装：

```bash
pip install ttkbootstrap tkinterdnd2 python-docx pdfplumber Pillow httpx python-dotenv pytest
```

可选依赖：

```bash
pip install reportlab
```

`reportlab` 只用于部分 PDF 测试；没有安装时相关测试会跳过。

## LLM 配置

在项目根目录创建 `.env`：

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

# 打包 Windows exe，输出到 dist/知识库助手/
pyinstaller build.spec --noconfirm
```

## 目录结构

```text
assets/       宠物精灵图和 UI 资源
converter/    docx/pdf/markdown 转换
docs/         设计说明、计划文件和参考图片
llm/          LLM client、wiki engine、prompt、lint、graph 数据
notes/        原始用户笔记，本地可写
search/       本地全文搜索
storage/      笔记保存逻辑
tests/        pytest 测试
ui/           Tkinter 面板、控件、搜索阅读器、聊天和图谱 UI
wiki/         LLM 维护的 wiki 输出，本地可写
```

## Wiki 工作流

知识库分为三层：

- `notes/`：原始资料，作为 source of truth。
- `wiki/`：LLM 维护的编译层，包含 source summaries、entity pages、concept pages、synthesis pages、`index.md` 和 `log.md`。
- schema/prompt：`AGENTS.md` 和 `llm/prompts.py` 约束 LLM 如何写入、查询和维护 wiki。

查询时会优先读取 `wiki/index.md` 找候选页面，再读取候选 wiki 页和一跳 `## Related` 页面。默认不读取 `notes/` 原文；只有用户明确要求“原文”“raw”“核对原文”“逐字”“第几页”等核查场景时，才读取少量匹配原文作为辅助证据。

## 打包说明

`build.spec` 会生成 one-folder bundle：

```text
dist/知识库助手/
```

打包后：

- `assets/` 从 PyInstaller `_MEIPASS` 读取。
- `notes/`、`wiki/`、`.env` 位于 exe 同级目录，方便用户写入。
- `tkinterdnd2/tkdnd` native 文件会被显式打包。

## 开发备注

- UI 采用多个透明 `Toplevel` 层：宠物、侧边栏、面板、阅读器。
- 面板主题来自 `ui/main_window.py` 的 `ACTIONS`。
- 动画集中在 `MainWindow._tick()`，不要为单个状态新增独立 `after()` 循环。
- 上传支持格式集中在 `ui/upload_tab.py` 的 `SUPPORTED`，新增格式只需扩展这里。
- 手写 Markdown renderer 在 `ui/markdown_render.py`，避免引入额外 markdown 依赖。
