# Query 优化计划

## Summary

将当前 query 从“直接全文关键词扫描 wiki 页面”升级为更符合 `docs/llm-wiki.md` 的 index-first wiki 查询流程。默认只读取 wiki compiled artifacts，不读取 `notes/` 原文；先用 `index.md` 找候选页，再读取候选页全文，并可按预算扩展一跳 `## Related` 邻居页，最后让 LLM 基于这些 wiki 页面回答并引用来源。

目标流程：

```text
用户问题
-> index.md 候选召回
-> 读取候选 wiki 页全文
-> 可选扩展 Related 邻居页
-> 必要时进入原文核查模式读取 notes 原文
-> 判断回答类型并选择对应 Markdown 输出结构
-> LLM 基于 wiki context 回答并引用页面
-> 记录 query log
-> 支持把高价值回答保存为 synthesis 页面
```

## Key Changes

- 新增 index-first query retrieval：
  - 新增 `_pick_query_index_candidates(question, wiki_dir, top_n)`。
  - 解析 `index.md` 的 Sources / Entities / Concepts 条目。
  - 用 `title / filename / summary` 做词面打分，不在候选阶段扫描所有 wiki 全文。
  - 优先召回 entity/concept，再按相关性召回 source summary。
  - 如果 `index.md` 不存在、为空或无命中，再 fallback 到现有 `_pick_relevant_pages()`。
- 候选确定后再读取全文：
  - 新增 query context builder，例如 `_build_query_context(question, candidates, wiki_dir)`。
  - 读取候选 wiki 页全文并格式化为带路径、类型、命中原因的 context。
  - 增加预算控制，避免文件变多后上下文失控：
    - `WIKI_QUERY_TOP_N = 6`
    - `WIKI_QUERY_RELATED_MAX = 4`
    - `WIKI_QUERY_CONTEXT_MAX_CHARS = 30000`
    - `WIKI_QUERY_PAGE_MAX_CHARS = 8000`
- 增加 Related 邻居扩展：
  - 新增 `_expand_query_related_pages(seed_pages, wiki_dir, max_pages)`。
  - 解析命中页的 `## Related` 链接，只扩展 1-hop。
  - 优先扩展 `sources/summary_*.md`，其次是强相关 entity/concept。
  - 默认不追到 `notes/` 原文。
- 更新 `QUERY_SYSTEM`：
  - 明确回答只能基于提供的 wiki pages。
  - 必须引用 wiki 页面路径。
  - 证据不足时直接说明不足。
  - 如果页面之间有冲突，要指出冲突来自哪些页面。
  - 如果答案适合沉淀为 wiki 页面，可以在末尾建议保存，并说明可保存的建议标题。
- 增加回答类型路由：
  - 新增 `_classify_query_answer_type(question)`，v1 用规则分类，不额外增加 LLM 调用。
  - 新增 `QUERY_TYPE_INSTRUCTIONS`，在通用 `QUERY_SYSTEM` 后追加类型化输出要求。
  - v1 仍返回 Markdown 文本流，不直接生成 PPTX、图片、canvas 或图表文件。
  - 支持的类型：
    - `direct_answer`：普通问答，直接回答。
    - `comparison_table`：比较/对比/vs，输出 Markdown 对比表。
    - `analysis_page`：综述/分析/整理成文章，输出 wiki-ready 分析页结构。
    - `timeline`：时间线/发展过程，输出时间线表或分阶段列表。
    - `outline`：提纲/框架，输出层级提纲。
    - `study_notes`：学习笔记/复习，输出笔记式小节、要点和问题。
    - `source_audit`：核对/证据/来源，重点列证据、冲突和引用。
    - `chart_spec`：图表/趋势/分布，输出 chart-ready 数据表和图表说明。
    - `slide_outline`：PPT/slides/presentation，输出逐页 slide outline。
- 为 query 写入 `log.md`：
  - 记录问题摘要和 used pages。
  - 无命中时也记录 `No relevant pages found`。
  - 不记录完整回答，避免 log 变臃肿。
- 同时实现两个增强能力：
  - `save_query_answer_as_wiki_page(question, answer, used_pages, wiki_dir)`：保存高价值回答为 synthesis 页面，并更新 `index.md` / `log.md`。
  - 原文核查模式：只有用户明确要求“原文 / raw / 论文中 / 第几页 / 核对原文 / 逐字 / 具体段落”等强触发词时，才读取匹配到的 `notes/` 原文；模型若在回答时发现 wiki 证据不足，只提示用户可用“核对原文”重新提问，不在同一轮里自动二次读取 raw notes。
- 扩展 index schema：
  - `index.md` 新增 `## Synthesis` section。
  - query retrieval 会读取 Synthesis 条目。
  - graph/lint/query 相关 index 解析逻辑必须容忍 Synthesis；不支持 synthesis 的旧调用保持兼容。

## Implementation Changes

- `llm/wiki_engine.py`：
  - 保持现有 `query_wiki(question, config, wiki_dir=...)` 调用兼容。
  - 新增 `QueryCandidate` 内部 dataclass，字段建议为 `path/title/kind/reason/score/source`。
  - 新增 `QueryResultMeta` dataclass，字段建议为 `question/answer_type/used_pages/raw_sources/suggested_save_title`。
  - 新增 `QueryAnswerType` 或等价字符串常量，以及 `_classify_query_answer_type(question)`。
  - 新增 `_read_index_catalog(wiki_dir)`，读取 `Sources / Entities / Concepts / Synthesis`；保留 `_read_index_entries()` 作为兼容包装，继续返回三元组。
  - 扩展 `_write_index(...)`，增加可选 `synthesis=None` 参数；旧调用不传该参数时行为不变。
  - 新增 query index retrieval、Related expansion、context builder 和 query log helper。
  - 新增 raw source 解析 helper，例如 `_query_needs_raw_source(question)` 和 `_find_raw_sources_for_query(question, used_pages, wiki_dir, notes_dir)`。
  - 新增 `save_query_answer_as_wiki_page(question, answer, used_pages, wiki_dir, answer_type="direct_answer", raw_sources=None)`，将回答保存到 `wiki/synthesis/query_<slug>.md`。
  - 改造 `query_wiki()` 为：
    1. 从 `index.md` 召回候选。
    2. 无候选时 fallback 当前全文检索。
    3. 读取候选页全文。
    4. 在预算内扩展 Related 邻居页。
    5. 如果问题含强触发词要求原文核查，读取预算内匹配的 `notes/` 原文并标记为 raw source context。
    6. 根据问题分类回答类型，并把对应 `QUERY_TYPE_INSTRUCTIONS[answer_type]` 追加到 system prompt。
    7. 若调用方传入可选 `on_meta` callback，则在流式回答前回传 `QueryResultMeta`，让 UI 缓存 used pages / raw sources / answer type。
    8. 调用 `chat_stream`。
    9. 在 generator 完成前追加 query log。
- `llm/prompts.py`：
  - 更新 `QUERY_SYSTEM`，加入引用、冲突、不足、保存建议和不读 raw notes 的规则。
  - 新增 `QUERY_TYPE_INSTRUCTIONS` 映射；每种类型只约束 Markdown 形态，不要求生成外部文件。
- `config.py`：
  - 新增 query 预算配置，均支持环境变量覆盖：
    - `WIKI_QUERY_TOP_N`
    - `WIKI_QUERY_RELATED_MAX`
    - `WIKI_QUERY_CONTEXT_MAX_CHARS`
    - `WIKI_QUERY_PAGE_MAX_CHARS`
    - `WIKI_QUERY_RAW_SOURCE_MAX`
    - `WIKI_QUERY_RAW_SOURCE_MAX_CHARS`
- UI：
  - `ChatTab` 增加“保存回答”按钮：仅在最近一次回答完成后可用，点击后调用 `save_query_answer_as_wiki_page(...)`。
  - `ChatTab` 在发起 query 时传入 `on_meta` callback，缓存 `last_question / last_answer_chunks / last_used_pages / last_raw_sources / last_answer_type`。
  - 流式回答完成后启用“保存回答”；保存成功后在聊天窗口追加一条 meta 提示和保存路径。
  - 原文核查不新增按钮；用户在问题中明确写“原文 / raw / 论文中 / 第几页 / 核对原文 / 逐字 / 具体段落”等关键词即可触发。

## Notes / Raw Source Policy

- Query 默认不读 `notes/` 原文，但本次实现显式触发的原文核查模式。
- Query 默认读取顺序：
  1. `index.md`
  2. `wiki/entities/*.md` 和 `wiki/concepts/*.md`
  3. `wiki/sources/summary_*.md`
  4. 显式原文核查模式下读取匹配的 `notes/` 原文
  5. `log.md` 仅作为后续可选上下文，本计划不默认加入回答 context
- 只有这些情况才进入原文核查模式：
  - 用户明确要求核对原文、论文原文、页码、逐字内容或具体段落。
  - 用户明确要求“根据原文确认 / raw source check / 查看原文证据”。
  - `source_audit` 回答类型本身不自动读取 raw notes；只有命中上述强触发词才读取。
- 如果 LLM 基于 wiki context 判断证据不足：
  - 本轮回答应说明 wiki 证据不足。
  - 回答末尾提示用户可用“核对原文”重新提问以触发 raw source verification。
  - v1 不做 `NEED_RAW_SOURCE_CHECK -> 二次读取 notes -> 二次回答` 的自动二阶段调用。
- 原文核查读取策略：
  - 优先从命中的 `sources/summary_*.md` frontmatter 或标题匹配回 `notes/` 文件。
  - 只读取与当前 query 相关的少量原文，受 `WIKI_QUERY_RAW_SOURCE_MAX` 和 `WIKI_QUERY_RAW_SOURCE_MAX_CHARS` 控制。
  - raw source context 必须在 prompt 中标记为辅助核查材料，回答仍应优先引用 wiki 页面；若引用 raw source，要明确标出 raw note 路径。

## Save Answer Policy

- 新增 `wiki/synthesis/` 目录用于保存 query 产生的高价值综合回答。
- 保存文件命名建议：
  - `synthesis/query_<slugified-question>.md`
  - 文件名冲突时沿用 `_1`, `_2` 后缀去重。
- 保存页面内容包含：
  - YAML frontmatter：`type: synthesis`, `created`, `question`
  - 原始问题
  - 模型回答
  - `## Sources`：列出 used wiki pages，raw notes 只在原文核查模式实际使用时列出
  - `## Related`：链接到 used entity/concept/source summary
  - `answer_type` 写入 frontmatter，便于后续把 `slide_outline`、`chart_spec` 等转成真正 artifact
- 保存后更新 `index.md`，新增并维护 `## Synthesis` section；同步扩展 index parser/write 以支持 Synthesis。
- 所有 index 消费者兼容 Synthesis：
  - query retrieval 会把 Synthesis 作为可召回页面。
  - graph 可以把 Synthesis 作为 `synthesis` kind 节点，或在 v1 中忽略但不得报错。
  - lint 的 index/disk drift 检查要识别 `wiki/synthesis/*.md`。
- 保存后追加 `log.md`：`query_save | <question summary>`。

## Test Plan

- Index-first retrieval：
  - 问题命中 `index.md` 中 concept/entity summary 时，返回对应 wiki 页面。
  - 候选阶段不读取 wiki 页面全文。
  - `index.md` 无命中时 fallback 到现有 `_pick_relevant_pages()`。
- Context budget：
  - 单页超过 `WIKI_QUERY_PAGE_MAX_CHARS` 时被截断。
  - 总 context 超过 `WIKI_QUERY_CONTEXT_MAX_CHARS` 时停止追加低分页面。
- Related expansion：
  - 命中 entity/concept 页后，可加入其 `## Related` 中的 source summary。
  - 只扩展 1-hop，且不超过 `WIKI_QUERY_RELATED_MAX`。
  - 不读取 `notes/` 原文。
- Raw source verification：
  - 普通问题不会读取 `notes/`。
  - 包含“原文 / raw / 论文中 / 第几页 / 核对原文 / 逐字 / 具体段落”等触发词的问题会读取匹配 raw note。
  - `source_audit` 只改变回答结构，不单独触发 raw note 读取。
  - raw note 读取受数量和字符预算限制。
  - raw source context 在 prompt 中被标记为辅助核查材料。
- Answer type routing：
  - “比较 / 对比 / vs / difference” 分类为 `comparison_table`。
  - “时间线 / timeline / 发展过程” 分类为 `timeline`。
  - “综述 / 分析 / 整理成文章” 分类为 `analysis_page`。
  - “PPT / slides / presentation” 分类为 `slide_outline`。
  - “图表 / chart / 趋势 / 分布” 分类为 `chart_spec`。
  - “核对 / 证据 / 来源” 分类为 `source_audit`。
  - “原文 / raw / 论文中 / 第几页 / 逐字 / 具体段落 / 核对原文” 额外触发 raw source verification。
  - 未命中规则时默认为 `direct_answer`。
  - 每类 prompt 输出结构符合预期，且仍引用 wiki 页面路径。
- Save answer：
  - `save_query_answer_as_wiki_page(...)` 创建 `wiki/synthesis/query_*.md`。
  - 保存页包含 question、answer、answer_type、sources、related links。
  - 保存后更新 `index.md` 的 Synthesis section，并追加 log。
  - `ChatTab` 通过 `on_meta` 获取 used_pages / raw_sources / answer_type，缓存完整回答 chunks，回答完成后可触发保存。
  - 保存后的 synthesis 页面能被后续 query 召回。
- Prompt behavior：
  - `QUERY_SYSTEM` 包含引用页面路径、证据不足、冲突说明、不默认读 raw notes 的约束。
- Query log：
  - query 完成后 `log.md` 追加 `query` 记录，包含问题摘要和 used pages。
  - 无命中时也记录 query log。
- Regression：
  - 现有 `query_wiki_empty_wiki` 和 `query_wiki_returns_generator` 继续通过。
  - 建议运行：
    `python -m pytest tests/test_wiki_engine.py tests/test_prompts.py -q`

## Assumptions

- v1 不引入 embedding、vector search 或外部检索工具。
- v1 不默认读取 `notes/` 原文；但实现显式触发的原文核查模式。
- v1 实现保存 query 回答为 synthesis 页面；保存由用户点击触发，不自动落盘。
- v1 的多回答类型只改变 Markdown 输出结构；不直接生成 PPTX、图片、canvas 或图表文件。
- v1 不实现模型自动二阶段 raw-source retry；证据不足时提示用户用“核对原文”重新提问。
- Related 扩展只做 1-hop，避免上下文膨胀。
- `query_wiki(...)` 外部调用方式保持兼容。
