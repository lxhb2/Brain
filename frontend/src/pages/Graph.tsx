import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeChange,
  applyNodeChanges,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Network, Loader2, SlidersHorizontal, LayoutGrid } from 'lucide-react'
import { api, type GraphData } from '@/api/client'
import { NoteNode, colorForDevice, type NoteNodeData } from '@/components/NoteNode'
import GraphFilters, { type GraphFiltersState } from '@/components/GraphFilters'
import NodeDetailDrawer from '@/components/NodeDetailDrawer'
import { UploadButton } from '@/components/UploadButton'
import { computeLayout } from '@/lib/layoutGraph'

const EDGE_COLOR: Record<string, string> = {
  semantic: '#22D3EE',
  keyword: '#6EA8FE',
  temporal: '#F5A623',
}

function GraphCanvas() {
  const [filters, setFilters] = useState<GraphFiltersState>({ device: '', app: '', status: '', q: '' })
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [rfNodes, setRfNodes] = useState<Node<NoteNodeData>[]>([])
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 1200, h: 800 })
  // 布局版本：仅在新数据到达或手动「重置布局」时递增，拖动节点不会触发
  const [layoutVersion, setLayoutVersion] = useState(0)

  // 拉取图谱（带筛选）
  const fetchGraph = useCallback(() => {
    setLoading(true)
    api
      .getGraph({ device: filters.device, app: filters.app, q: filters.q, status: filters.status })
      .then((g) => {
        setGraph(g)
        setSelectedId(null)
      })
      .finally(() => setLoading(false))
  }, [filters])

  // 筛选变化时刷新（关键词防抖）
  useEffect(() => {
    const t = setTimeout(fetchGraph, filters.q ? 350 : 0)
    return () => clearTimeout(t)
  }, [fetchGraph])

  // 容器尺寸
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect
      setSize({ w: r.width, h: r.height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const devices = useMemo(
    () => Array.from(new Set((graph?.nodes ?? []).map((n) => n.source_device).filter(Boolean) as string[])),
    [graph],
  )
  const apps = useMemo(
    () => Array.from(new Set((graph?.nodes ?? []).map((n) => n.source_app).filter(Boolean) as string[])),
    [graph],
  )

  // 计算每个节点的连接数（degree），用于决定圆点大小
  const degreeMap = useMemo(() => {
    const m = new Map<number, number>()
    if (!graph) return m
    for (const e of graph.edges) {
      m.set(e.source, (m.get(e.source) ?? 0) + 1)
      m.set(e.target, (m.get(e.target) ?? 0) + 1)
    }
    return m
  }, [graph])

  // 计算布局 + 生成 React Flow 节点
  // 仅在图谱数据变化或手动重置布局时重新计算，拖动/选中节点不会重置位置
  useEffect(() => {
    if (!graph) return
    const ids = graph.nodes.map((n) => n.id)
    const layout = computeLayout({
      nodeIds: ids,
      edges: graph.edges,
      width: Math.max(size.w, 600),
      height: Math.max(size.h, 400),
      iterations: 180,
    })
    const nodes: Node<NoteNodeData>[] = graph.nodes.map((n) => {
      const pos = layout.get(n.id) ?? { x: 0, y: 0 }
      return {
        id: String(n.id),
        type: 'noteNode',
        position: { x: pos.x, y: pos.y },
        // 不在此设置 selected，交给 applyNodeChanges 维护，避免选中时重置布局
        data: { ...n, isNeighbor: false, degree: degreeMap.get(n.id) ?? 0 },
      }
    })
    setRfNodes(nodes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, layoutVersion])

  const edges = useMemo(() => {
    if (!graph) return []
    return graph.edges.map((e, i) => {
      const color = EDGE_COLOR[e.link_type ?? 'semantic'] ?? '#6EA8FE'
      return {
        id: `e-${e.source}-${e.target}-${i}`,
        source: String(e.source),
        target: String(e.target),
        animated: e.weight > 0.6,
        style: { stroke: color, strokeWidth: 0.5 + e.weight * 2.5, opacity: 0.35 + e.weight * 0.5 },
      }
    })
  }, [graph])

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setRfNodes((nds) => applyNodeChanges(changes, nds) as Node<NoteNodeData>[])
      for (const c of changes) {
        if (c.type === 'select' && c.selected) {
          setSelectedId(Number(c.id))
        }
      }
    },
    [],
  )

  const nodeTypes = useMemo(() => ({ noteNode: NoteNode }), [])

  const activeFilterCount = [filters.device, filters.app, filters.status, filters.q].filter(Boolean).length

  return (
    <div className="flex h-full w-full">
      {/* 桌面端常驻筛选栏 */}
      <div className="hidden md:block">
        <GraphFilters
          state={filters}
          onChange={setFilters}
          devices={devices}
          apps={apps}
          nodeCount={graph?.nodes.length ?? 0}
          edgeCount={graph?.edges.length ?? 0}
        />
      </div>

      <div className="relative flex-1" ref={containerRef}>
        {/* 移动端顶部工具栏 */}
        <div className="safe-top absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-2 px-3 py-2 md:hidden">
          <button
            onClick={() => setShowFilters(true)}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-void-300/80 px-3 py-2 text-xs text-starlight backdrop-blur-md"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            筛选
            {activeFilterCount > 0 && (
              <span className="rounded-full bg-flux/20 px-1.5 py-0.5 font-mono text-[9px] text-flux">{activeFilterCount}</span>
            )}
          </button>
          <div className="flex items-center gap-2">
            <UploadButton onUploaded={fetchGraph} />
            <div className="rounded-lg border border-white/5 bg-void-300/70 px-2.5 py-1.5 font-mono text-[10px] text-dust backdrop-blur-md">
              {graph?.nodes.length ?? 0} 节点
            </div>
          </div>
        </div>

        {/* 移动端筛选 Sheet */}
        {showFilters && (
          <div className="absolute inset-0 z-30 md:hidden">
            <GraphFilters
              state={filters}
              onChange={setFilters}
              devices={devices}
              apps={apps}
              nodeCount={graph?.nodes.length ?? 0}
              edgeCount={graph?.edges.length ?? 0}
              onClose={() => setShowFilters(false)}
            />
          </div>
        )}

        {/* 空状态 */}
        {!loading && graph && graph.nodes.length === 0 && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 px-6 text-center text-dust">
            <Network className="h-10 w-10 opacity-40" strokeWidth={1} />
            <div className="font-display text-lg text-starlight/70">星空尚空</div>
            <p className="max-w-xs text-sm">
              将手写笔记（PDF / PNG / JPG）放入中转机的 <code className="rounded bg-white/5 px-1 font-mono text-xs">synced_notes/</code> 目录，系统会自动监听并入库。
            </p>
          </div>
        )}

        {loading && (
          <div className="absolute right-4 top-20 z-20 flex items-center gap-2 rounded-lg border border-white/10 bg-void-300/80 px-3 py-2 backdrop-blur-md md:top-4">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-flux" />
            <span className="font-mono text-xs text-dust">绘制星座中…</span>
          </div>
        )}

        {/* 桌面端上传按钮（右上角） */}
        <div className="absolute right-4 top-4 z-20 hidden md:block">
          <UploadButton onUploaded={fetchGraph} />
        </div>

        <ReactFlow
          nodes={rfNodes}
          edges={edges as unknown as Edge[]}
          onNodesChange={onNodesChange}
          onNodeClick={(_e, node) => setSelectedId(Number(node.id))}
          onPaneClick={() => setSelectedId(null)}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
          minZoom={0.15}
          maxZoom={2.5}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{ type: 'smoothstep' }}
          // 允许拖动节点重新排列
          nodesDraggable
          nodesConnectable={false}
          // 触摸优化：允许双指缩放与拖拽
          zoomOnScroll={true}
          panOnDrag={true}
        >
          <Background color="#1A2240" gap={28} size={1} />
          <Controls showInteractive={false} className="hidden md:block" />
          <MiniMap
            className="hidden md:block"
            nodeColor={(n) => {
              const d = n.data as NoteNodeData | undefined
              return colorForDevice(d?.source_device ?? null)
            }}
            nodeStrokeColor="#F5A623"
            nodeStrokeWidth={0}
            maskColor="rgba(11,16,32,0.7)"
          />
        </ReactFlow>

        {/* 图例（设备颜色 + 链接类型，移动端简化） */}
        <div className="absolute bottom-4 left-3 z-10 flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/5 bg-void-300/70 px-2.5 py-1.5 backdrop-blur-md md:gap-3 md:px-3 md:py-2">
            <span className="hidden font-mono text-[10px] uppercase tracking-wider text-dust/70 md:inline">设备</span>
            {devices.length > 0 ? (
              devices.map((d) => (
                <span key={d} className="flex items-center gap-1 font-mono text-[10px] text-starlight/70 md:text-[11px]">
                  <span className="h-2 w-2 rounded-full" style={{ background: colorForDevice(d) }} />
                  {d}
                </span>
              ))
            ) : (
              <span className="flex items-center gap-1 font-mono text-[10px] text-starlight/70 md:text-[11px]">
                <span className="h-2 w-2 rounded-full" style={{ background: colorForDevice(null) }} />
                未知
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/5 bg-void-300/70 px-2.5 py-1.5 backdrop-blur-md md:gap-3 md:px-3 md:py-2">
            <span className="hidden font-mono text-[10px] uppercase tracking-wider text-dust/70 md:inline">链接</span>
            {Object.entries(EDGE_COLOR).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1 font-mono text-[10px] text-starlight/70 md:text-[11px]">
                <span className="h-0.5 w-3 rounded-full md:w-4" style={{ background: v }} />
                {k === 'semantic' ? '语义' : k === 'keyword' ? '关键词' : '时间'}
              </span>
            ))}
          </div>
        </div>

        {/* 重置布局按钮 */}
        <button
          onClick={() => setLayoutVersion((v) => v + 1)}
          title="重新计算力导向布局"
          className="absolute bottom-4 right-3 z-10 flex items-center gap-1.5 rounded-lg border border-white/10 bg-void-300/70 px-2.5 py-1.5 font-mono text-[11px] text-starlight/80 backdrop-blur-md transition-all hover:border-flux/30 hover:text-flux active:scale-95 md:px-3"
        >
          <LayoutGrid className="h-3.5 w-3.5" strokeWidth={1.5} />
          <span className="hidden sm:inline">重置布局</span>
        </button>

        <NodeDetailDrawer noteId={selectedId} onClose={() => setSelectedId(null)} />
      </div>
    </div>
  )
}

export default function Graph() {
  return (
    <ReactFlowProvider>
      <GraphCanvas />
    </ReactFlowProvider>
  )
}
