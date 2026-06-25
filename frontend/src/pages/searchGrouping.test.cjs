const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')
const vm = require('node:vm')

function loadTsModule(relativePath) {
  const filename = path.join(__dirname, relativePath)
  const source = fs.readFileSync(filename, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(output, {
    exports: module.exports,
    module,
    require,
  }, { filename })
  return module.exports
}

test('buildCollapsibleGroups filters empty groups and localizes wiki labels', () => {
  const { buildCollapsibleGroups } = loadTsModule('./searchGrouping.ts')
  const groups = [
    { kind: 'source', label: 'Sources', items: [{ path: 'sources/a.md' }] },
    { kind: 'concept', label: 'Concepts', items: [] },
    { kind: 'entity', label: 'Entities', items: [{ path: 'entities/openai.md' }] },
  ]

  const visible = buildCollapsibleGroups(groups, new Set(['entity']))

  assert.deepEqual(visible.map((group) => ({
    kind: group.kind,
    label: group.displayLabel,
    count: group.count,
    collapsed: group.collapsed,
  })), [
    { kind: 'source', label: '来源', count: 1, collapsed: false },
    { kind: 'entity', label: '实体', count: 1, collapsed: true },
  ])
})

test('buildTagGroups groups files by every tag', () => {
  const { buildTagGroups } = loadTsModule('./searchGrouping.ts')
  const items = [
    { path: 'a.md', tags: ['AI', '项目'] },
    { path: 'b.pdf', tags: ['AI'] },
    { path: 'c.md', tags: [] },
  ]

  const groups = buildTagGroups(items, new Set(['tag:项目']))

  assert.deepEqual(Array.from(groups, (group) => ({
    kind: group.kind,
    label: group.displayLabel,
    count: group.count,
    collapsed: group.collapsed,
    paths: Array.from(group.items, (item) => item.path),
  })), [
    { kind: 'tag:ai', label: '#AI', count: 2, collapsed: false, paths: ['a.md', 'b.pdf'] },
    { kind: 'tag:项目', label: '#项目', count: 1, collapsed: true, paths: ['a.md'] },
  ])
})

test('source result text wraps inside bounded cards', () => {
  const css = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  assert.match(css, /\.result-snippet\s*\{[^}]*white-space:\s*normal;/s)
  assert.match(css, /\.result-snippet\s*\{[^}]*overflow:\s*hidden;/s)
  assert.match(css, /\.result-snippet\s*\{[^}]*-webkit-line-clamp:\s*2;/s)
  assert.match(css, /\.result-item\s*\{[^}]*padding:\s*14px 16px 18px;/s)
  assert.match(css, /\.result-item\s*\{[^}]*gap:\s*8px;/s)
  assert.match(css, /\.result-name,\s*\n\.result-snippet\s*\{[^}]*overflow-wrap:\s*anywhere;/s)
})

test('preview metadata controls stay compact', () => {
  const page = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')
  const css = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  assert.match(page, /<div className="preview-meta-bar">/)
  assert.match(page, /<div className="tag-editor compact">/)
  assert.match(css, /\.preview-meta-bar\s*\{[^}]*display:\s*grid;/s)
  assert.match(css, /\.tag-editor\.compact\s*\{[^}]*margin-bottom:\s*8px;/s)
  assert.match(css, /\.tag-editor\.compact input\s*\{[^}]*height:\s*32px;/s)
})

test('search errors stay compact above the result grid', () => {
  const page = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')
  const css = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  assert.match(page, /className="search-error"/)
  assert.match(css, /\.search-error\s*\{[^}]*max-height:\s*96px;/s)
  assert.match(css, /\.search-error\s*\{[^}]*overflow:\s*auto;/s)
})

test('wiki markdown links resolve to internal wiki paths', () => {
  const { parseWikilinkTarget, resolveWikiPageLink } = loadTsModule('./wikiLinks.ts')

  assert.equal(resolveWikiPageLink('sources/summary_a.md', '../entities/openai.md'), 'entities/openai.md')
  assert.equal(resolveWikiPageLink('entities/openai.md', 'sources/summary_a.md#出处'), 'sources/summary_a.md')
  assert.equal(resolveWikiPageLink('concepts/llm.md', './prompting.md'), 'concepts/prompting.md')
  assert.equal(resolveWikiPageLink('', 'concepts/llm.md'), 'concepts/llm.md')
  assert.equal(resolveWikiPageLink('entities/openai.md', 'https://example.com'), null)
  assert.equal(resolveWikiPageLink('entities/openai.md', '../notes/private.md'), null)
  const parsed = parseWikilinkTarget('sources/summary_a.md|来源 A')
  assert.equal(parsed.target, 'sources/summary_a.md')
  assert.equal(parsed.label, '来源 A')
})

test('search preview and chat render internal links as navigable controls', () => {
  const searchPage = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')
  const chatPage = fs.readFileSync(path.join(__dirname, 'ChatPage.tsx'), 'utf8')

  assert.match(searchPage, /onWikiLink=\{\(path\) => navigatePanel\('search', token, \{ scope: 'wiki', path \}\)\}/)
  assert.match(searchPage, /currentPath=\{preview.relative_path\}/)
  assert.match(chatPage, /MarkdownInline[^]*onWikiLink=\{\(path\) => navigatePanel\('search', token, \{ scope: 'wiki', path \}\)\}/)
  assert.doesNotMatch(chatPage, /<pre className="answer">\{turn\.answer \|\| '\.\.\.'\}<\/pre>/)
})

test('search opens requested raw note paths even when they are not in source list', () => {
  const searchPage = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')

  assert.match(searchPage, /async function loadRequestedNotePreview\(path: string\)/)
  assert.match(searchPage, /else if \(requestedPath && previewFirst && nextMode === 'sources'\)/)
})

test('saving tags refreshes the current tag result list', () => {
  const searchPage = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')

  assert.match(searchPage, /if \(mode === 'tag'\) \{\s*await runSearch\('tag', query, false\)/s)
})

test('tag mode uses collapsible tag groups', () => {
  const searchPage = fs.readFileSync(path.join(__dirname, 'SearchPage.tsx'), 'utf8')

  assert.match(searchPage, /buildTagGroups\(results, collapsedKinds\)/)
})

test('chat keeps history across route changes and offers manual clear', () => {
  const chatPage = fs.readFileSync(path.join(__dirname, 'ChatPage.tsx'), 'utf8')

  assert.match(chatPage, /let cachedTurns: Turn\[\] = \[\]/)
  assert.match(chatPage, /setTurns\(cachedTurns\)/)
  assert.match(chatPage, /function clearChat\(\)/)
  assert.match(chatPage, /<Button variant="ghost" htmlType="button" onClick=\{clearChat\}>[^]*清空[^]*<\/Button>/)
})

test('chat only auto-scrolls when user is already near the bottom', () => {
  const chatPage = fs.readFileSync(path.join(__dirname, 'ChatPage.tsx'), 'utf8')

  assert.match(chatPage, /function isNearConversationBottom\(/)
  assert.match(chatPage, /shouldFollowRef\.current/)
  assert.match(chatPage, /onScroll=\{handleConversationScroll\}/)
  assert.match(chatPage, /if \(node && shouldFollowRef\.current\) \{\s*node\.scrollTop = node\.scrollHeight/s)
})

test('panel navigation lives in the titlebar and scrollbars use zelda styling', () => {
  const shell = fs.readFileSync(path.join(__dirname, '../components/PanelShell.tsx'), 'utf8')
  const styles = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  const titlebar = shell.split('<div className="app-titlebar">', 2)[1].split('<SheikahBackground', 1)[0]
  assert.match(titlebar, /<nav className="panel-nav" aria-label="Panel navigation">/)
  assert.doesNotMatch(shell, /<header className="panel-header">/)
  assert.match(styles, /::-webkit-scrollbar\s*\{/)
  assert.match(styles, /::-webkit-scrollbar-thumb\s*\{[^}]*background:\s*linear-gradient/s)
  assert.match(styles, /scrollbar-color:\s*#3cd3fc rgba\(10, 20, 40, 0\.58\);/)
})

test('ingest page shows source files while collecting wiki content', () => {
  const ingestPage = fs.readFileSync(path.join(__dirname, 'IngestPage.tsx'), 'utf8')

  assert.match(ingestPage, /previewLibraryFile/)
  assert.match(ingestPage, /previewNote/)
  assert.match(ingestPage, /function loadSourcePreview\(path: string\)/)
  assert.match(ingestPage, /<Card variant="sheikah" title="源文件">/)
  assert.match(ingestPage, /className="source-file-frame"/)
})

test('ingest compose stays stable when launched from inbox in a narrow panel', () => {
  const css = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  assert.match(css, /\.ingest-compose\s*\{[^}]*justify-content:\s*stretch;/s)
  assert.match(css, /\.ingest-compose\s+button\s*\{[^}]*white-space:\s*nowrap;/s)
  assert.match(css, /@media \(max-width:\s*1280px\)\s*\{[^}]*\.ingest-workbench\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s)
})

test('inbox ingest actions stay compact inside file cards', () => {
  const uploadPage = fs.readFileSync(path.join(__dirname, 'UploadPage.tsx'), 'utf8')
  const css = fs.readFileSync(path.join(__dirname, '../styles.css'), 'utf8')

  assert.match(uploadPage, /className=\{`inbox-item result-item/)
  assert.match(uploadPage, /<div className="inbox-file-info">/)
  assert.match(css, /\.inbox-item\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) max-content;/s)
  assert.match(css, /\.inbox-item\s+button\s*\{[^}]*width:\s*auto;/s)
  assert.match(css, /\.inbox-item\s+button\s*\{[^}]*white-space:\s*nowrap;/s)
})

test('inbox files expose a delete action', () => {
  const api = fs.readFileSync(path.join(__dirname, '../api.ts'), 'utf8')
  const uploadPage = fs.readFileSync(path.join(__dirname, 'UploadPage.tsx'), 'utf8')

  assert.match(api, /export function deleteInboxItem\(token: string, path: string\)/)
  assert.match(api, /method:\s*'DELETE'/)
  assert.match(uploadPage, /deleteInboxItem/)
  assert.match(uploadPage, />\s*删除\s*<\/Button>/)
})
