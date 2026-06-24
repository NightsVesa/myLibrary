import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Dialog, Loading } from 'zelda-hyrule-ui'
import { loadGraph, navigatePanel } from '../api'
import { PanelShell } from '../components/PanelShell'
import type { GraphEdge, GraphNode, GraphPayload } from '../types'

const KIND_LABELS: Record<string, string> = {
  source: '来源',
  entity: '实体',
  concept: '概念',
}

const KIND_COLORS: Record<string, string> = {
  source: '#7c3aed',
  entity: '#10b981',
  concept: '#f59e0b',
}

const DEGREE_OPTIONS = [0, 1, 2, 5]
const GRAPH_W = 900
const GRAPH_H = 520

type GraphPageProps = {
  token: string
}

type LayoutNode = GraphNode & {
  x: number
  y: number
}

function kindLabel(kind: string) {
  return KIND_LABELS[kind] ?? kind
}

function nodeMatches(node: GraphNode, query: string) {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return node.title.toLowerCase().includes(needle) || node.id.toLowerCase().includes(needle)
}

function layoutNodes(nodes: GraphNode[]): LayoutNode[] {
  if (nodes.length === 0) return []
  const sorted = [...nodes].sort((a, b) => b.degree - a.degree || a.title.localeCompare(b.title))
  const cx = GRAPH_W / 2
  const cy = GRAPH_H / 2
  if (sorted.length === 1) return [{ ...sorted[0], x: cx, y: cy }]
  return sorted.map((node, index) => {
    const angle = (Math.PI * 2 * index) / sorted.length - Math.PI / 2
    const ring = 0.72 + (index % 3) * 0.12
    const rx = GRAPH_W * 0.38 * ring
    const ry = GRAPH_H * 0.35 * ring
    return {
      ...node,
      x: cx + Math.cos(angle) * rx,
      y: cy + Math.sin(angle) * ry,
    }
  })
}

function visibleEdges(edges: GraphEdge[], visibleIds: Set<string>) {
  return edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
}

export function GraphPage({ token }: GraphPageProps) {
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [kinds, setKinds] = useState<Set<string>>(new Set(['source', 'entity', 'concept']))
  const [minDegree, setMinDegree] = useState(0)
  const [showQuality, setShowQuality] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  async function refreshGraph() {
    setLoading(true)
    setError('')
    try {
      const payload = await loadGraph(token)
      setGraph(payload)
      setSelectedId((current) => (
        current && payload.nodes.some((node) => node.id === current) ? current : null
      ))
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '图谱加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refreshGraph()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filteredNodes = useMemo(() => {
    if (!graph) return []
    return graph.nodes.filter((node) => (
      kinds.has(node.kind)
      && node.degree >= minDegree
      && nodeMatches(node, query)
    ))
  }, [graph, kinds, minDegree, query])

  const layout = useMemo(() => layoutNodes(filteredNodes), [filteredNodes])
  const nodeMap = useMemo(() => new Map(layout.map((node) => [node.id, node])), [layout])
  const visibleIds = useMemo(() => new Set(layout.map((node) => node.id)), [layout])
  const edges = useMemo(() => visibleEdges(graph?.edges ?? [], visibleIds), [graph, visibleIds])

  const neighborIds = useMemo(() => {
    if (!selectedId) return new Set<string>()
    const neighbors = new Set<string>()
    for (const edge of graph?.edges ?? []) {
      if (edge.source === selectedId) neighbors.add(edge.target)
      if (edge.target === selectedId) neighbors.add(edge.source)
    }
    return neighbors
  }, [graph, selectedId])

  const selected = selectedId ? (graph?.nodes.find((node) => node.id === selectedId) ?? null) : null
  const topNodes = useMemo(
    () => [...(graph?.nodes ?? [])].filter((node) => node.degree > 0).sort((a, b) => b.degree - a.degree).slice(0, 10),
    [graph],
  )
  const subtitle = graph
    ? `${filteredNodes.length}/${graph.nodes.length} 节点 · ${edges.length} 关系`
    : '正在读取 wiki 关系'

  function toggleKind(kind: string) {
    setKinds((current) => {
      const next = new Set(current)
      if (next.has(kind)) {
        if (next.size > 1) next.delete(kind)
      } else {
        next.add(kind)
      }
      return next
    })
  }

  function qualityClass(node: GraphNode) {
    if (!showQuality || !graph) return ''
    if (graph.diagnostics.missing.includes(node.id)) return ' missing'
    if (graph.diagnostics.orphan.includes(node.id)) return ' orphan'
    if (graph.diagnostics.hub.includes(node.id)) return ' hub'
    return ''
  }

  return (
    <PanelShell
      active="graph"
      eyebrow="SHEIKAH GRAPH"
      title="知识图谱"
      subtitle={subtitle}
      token={token}
    >
      <section className="graph-toolbar">
        <input
          className="text-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索节点标题或路径"
        />
        <div className="mode-row graph-modes">
          {['source', 'entity', 'concept'].map((kind) => (
            <button
              className={kinds.has(kind) ? 'mode active' : 'mode'}
              key={kind}
              onClick={() => toggleKind(kind)}
              type="button"
            >
              {kindLabel(kind)}
            </button>
          ))}
          {DEGREE_OPTIONS.map((degree) => (
            <button
              className={degree === minDegree ? 'mode active' : 'mode'}
              key={degree}
              onClick={() => setMinDegree(degree)}
              type="button"
            >
              {degree === 0 ? '全部' : `${degree}+`}
            </button>
          ))}
        </div>
        <div className="preview-actions graph-actions">
          <Button variant="ghost" size="small" onClick={() => setShowQuality((value) => !value)}>
            {showQuality ? '隐藏质量' : '显示质量'}
          </Button>
          <Button variant="sheikah" size="small" loading={loading} onClick={() => void refreshGraph()}>
            刷新
          </Button>
        </div>
      </section>

      {error && (
        <Dialog type="sheikah" speaker="Panel" showContinue={false}>
          {error}
        </Dialog>
      )}

      <section className="graph-grid">
        <Card variant="sheikah" title="Map" className="graph-card">
          {loading && !graph && <Loading tip="Reading wiki..." />}
          {graph && graph.nodes.length === 0 && <p className="empty">wiki/index.md 还没有可绘制的节点</p>}
          {graph && graph.nodes.length > 0 && (
            <svg className="graph-svg" viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`} role="img" aria-label="知识图谱">
              <defs>
                <filter id="graphGlow" x="-40%" y="-40%" width="180%" height="180%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <g className="graph-edges">
                {edges.map((edge) => {
                  const source = nodeMap.get(edge.source)
                  const target = nodeMap.get(edge.target)
                  if (!source || !target) return null
                  const active = selectedId && (edge.source === selectedId || edge.target === selectedId)
                  return (
                    <line
                      key={`${edge.source}-${edge.target}`}
                      className={active ? 'graph-edge active' : 'graph-edge'}
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                    />
                  )
                })}
              </g>
              <g className="graph-nodes">
                {layout.map((node) => {
                  const selectedNode = node.id === selectedId
                  const dimmed = selectedId && !selectedNode && !neighborIds.has(node.id)
                  const radius = Math.max(8, Math.min(24, 9 + node.degree * 2))
                  return (
                    <g
                      className={`graph-node ${selectedNode ? 'selected' : ''}${dimmed ? ' dimmed' : ''}${qualityClass(node)}`}
                      key={node.id}
                      onClick={() => setSelectedId(node.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={radius}
                        fill={KIND_COLORS[node.kind] ?? '#3cd3fc'}
                        filter={selectedNode ? 'url(#graphGlow)' : undefined}
                      />
                      <text x={node.x + radius + 5} y={node.y + 4}>
                        {node.title}
                      </text>
                      <title>{`${node.title} · ${kindLabel(node.kind)} · ${node.degree} 关系`}</title>
                    </g>
                  )
                })}
              </g>
            </svg>
          )}
        </Card>

        <Card variant="sheikah" title="Signals" className="graph-side-card">
          <div className="graph-stat-row">
            <span>孤立</span>
            <strong>{graph?.diagnostics.orphan.length ?? 0}</strong>
          </div>
          <div className="graph-stat-row">
            <span>缺页</span>
            <strong>{graph?.diagnostics.missing.length ?? 0}</strong>
          </div>
          <div className="graph-stat-row">
            <span>枢纽</span>
            <strong>{graph?.diagnostics.hub.length ?? 0}</strong>
          </div>

          <h2 className="graph-side-title">Top 连接度</h2>
          <div className="graph-rank-list">
            {topNodes.map((node) => (
              <button
                className={node.id === selectedId ? 'graph-rank selected' : 'graph-rank'}
                key={node.id}
                onClick={() => setSelectedId(node.id)}
                type="button"
              >
                <span>{node.title}</span>
                <strong>{node.degree}</strong>
              </button>
            ))}
            {topNodes.length === 0 && <p className="empty">暂无连接关系</p>}
          </div>

          <h2 className="graph-side-title">节点详情</h2>
          {!selected && <p className="empty">点击节点查看摘要和路径</p>}
          {selected && (
            <article className="graph-detail">
              <p className="result-name">{selected.title}</p>
              <p className="tag-row">
                <span>{kindLabel(selected.kind)}</span>
                <span>{selected.degree} 关系</span>
                {!selected.exists && <span>缺页</span>}
              </p>
              <p>{selected.summary || '没有摘要'}</p>
              <code>{selected.path || selected.id}</code>
              {selected.exists && (
                <div className="graph-detail-actions">
                  <Button
                    variant="sheikah"
                    size="small"
                    onClick={() => navigatePanel('search', token, { scope: 'wiki', path: selected.id })}
                  >
                    查看 MD
                  </Button>
                </div>
              )}
            </article>
          )}
        </Card>
      </section>
    </PanelShell>
  )
}
