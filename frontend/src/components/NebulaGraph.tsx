import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import * as d3 from 'd3-force'
import { Layers, FileText, Sparkles, Maximize2 } from 'lucide-react'

interface NebulaNode extends d3.SimulationNodeDatum {
  id: string
  type: 'note' | 'card'
  ref_id: number
  title: string
  subtitle?: string | null
}

interface NebulaEdge {
  source: string
  target: string
  source_type: 'note' | 'card'
  target_type: 'note' | 'card'
  weight: number
  reason: string | null
}

interface NebulaGraphProps {
  data: { nodes: NebulaNode[]; edges: NebulaEdge[] }
  centerNodeId?: string  // 高亮居中的节点
}

/**
 * Obsidian 风格力导向图谱（星云布局）。
 * - 节点：note（圆形）+ card（六边形/菱形）
 * - 边：根据 source_type/target_type 染色
 * - 力：斥力 + 链接引力 + 向心力
 * - 交互：可拖拽节点，hover 高亮邻居
 */
export default function NebulaGraph({ data, centerNodeId }: NebulaGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 1200, h: 800 })
  const [hoverId, setHoverId] = useState<string | null>(null)
  // 用 ref 存 simulation，避免每次 render 重建
  const simRef = useRef<d3.Simulation<NebulaNode, undefined> | null>(null)
  const nodesRef = useRef<NebulaNode[]>([])
  const edgesRef = useRef<Array<d3.SimulationLinkDatum<NebulaNode> & { reason: string | null }>>([])

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

  // 数据变化时重建 simulation
  useEffect(() => {
    if (!data.nodes.length) {
      nodesRef.current = []
      edgesRef.current = []
      simRef.current?.stop()
      return
    }
    // 准备 nodes / links（d3 期望 link.source/target 为 node 引用或 index）
    const nodes: NebulaNode[] = data.nodes.map((n) => ({ ...n }))
    const nodeById = new Map(nodes.map((n) => [n.id, n]))
    const links: Array<d3.SimulationLinkDatum<NebulaNode> & { reason: string | null }> = []
    for (const e of data.edges) {
      const s = nodeById.get(e.source)
      const t = nodeById.get(e.target)
      if (!s || !t) continue
      links.push({ source: s, target: t, reason: e.reason })
    }
    nodesRef.current = nodes
    edgesRef.current = links

    // 中心节点放在画布中心
    const cx = size.w / 2
    const cy = size.h / 2
    if (centerNodeId) {
      const center = nodes.find((n) => n.id === centerNodeId)
      if (center) {
        center.x = cx
        center.y = cy
        center.fx = cx
        center.fy = cy
      }
    }

    // 构造 simulation
    const sim = d3
      .forceSimulation<NebulaNode>(nodes)
      .force('charge', d3.forceManyBody<NebulaNode>().strength((n) => n.type === 'card' ? -350 : -120))
      .force(
        'link',
        d3
          .forceLink<NebulaNode, d3.SimulationLinkDatum<NebulaNode>>(links)
          .id((d) => d.id)
          .distance((l: any) => {
            // card-note 链接短一些，让卡片紧贴笔记
            const s = l.source as NebulaNode
            const t = l.target as NebulaNode
            if (s.type === 'card' || t.type === 'card') return 80
            return 120
          })
          .strength(0.5),
      )
      .force('center', d3.forceCenter(cx, cy))
      .force('collide', d3.forceCollide<NebulaNode>().radius((n) => (n.type === 'card' ? 32 : 18)))
      .alpha(1)
      .alphaDecay(0.025)

    sim.on('tick', () => {
      // 触发 React 重绘（用 setHoverId 的副作用太 hack，改用 forceUpdate）
      // 这里我们用 SVG 直接操作，所以 trigger 一次 re-render
      setTickCounter((c) => c + 1)
    })

    simRef.current = sim

    return () => {
      sim.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, centerNodeId, size.w, size.h])

  // tick 触发重绘
  const [, setTickCounter] = useState(0)

  // 拖拽处理
  const draggingNode = useRef<NebulaNode | null>(null)
  const handlePointerDown = (e: React.PointerEvent, node: NebulaNode) => {
    e.stopPropagation()
    ;(e.target as Element).setPointerCapture(e.pointerId)
    draggingNode.current = node
    node.fx = node.x
    node.fy = node.y
    simRef.current?.alphaTarget(0.3).restart()
  }
  const handlePointerMove = (e: React.PointerEvent) => {
    if (!draggingNode.current || !svgRef.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    draggingNode.current.fx = x
    draggingNode.current.fy = y
  }
  const handlePointerUp = (e: React.PointerEvent) => {
    if (draggingNode.current) {
      // 释放固定（除非是中心节点）
      if (draggingNode.current.id !== centerNodeId) {
        draggingNode.current.fx = null
        draggingNode.current.fy = null
      }
      draggingNode.current = null
      simRef.current?.alphaTarget(0)
    }
    ;(e.target as Element).releasePointerCapture?.(e.pointerId)
  }

  // 计算邻居集合（用于 hover 高亮）
  const hoverNeighbors = useMemo(() => {
    if (!hoverId) return null
    const set = new Set<string>([hoverId])
    for (const l of edgesRef.current) {
      const s = (l.source as any).id ?? l.source
      const t = (l.target as any).id ?? l.target
      if (s === hoverId) set.add(t)
      if (t === hoverId) set.add(s)
    }
    return set
  }, [hoverId, data])

  if (!data.nodes.length) {
    return (
      <div ref={containerRef} className="flex h-full items-center justify-center text-dust/60">
        <div className="text-center">
          <Layers className="mx-auto mb-2 h-8 w-8 opacity-40" strokeWidth={1.2} />
          <p className="text-xs">暂无图谱数据</p>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-void-500/20">
      <svg
        ref={svgRef}
        width={size.w}
        height={size.h}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        className="block"
      >
        {/* 边 */}
        <g>
          {edgesRef.current.map((l, i) => {
            const s = l.source as NebulaNode
            const t = l.target as NebulaNode
            if (s.x == null || t.x == null || s.y == null || t.y == null) return null
            const isHighlighted = hoverNeighbors && (hoverNeighbors.has(s.id) && hoverNeighbors.has(t.id))
            const isCardLink = s.type === 'card' || t.type === 'card'
            const color = isCardLink ? '#A78BFA' : '#3B82F6'
            return (
              <line
                key={i}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke={color}
                strokeOpacity={isHighlighted ? 0.8 : hoverNeighbors ? 0.1 : 0.3}
                strokeWidth={isCardLink ? 1.5 : 1}
                strokeDasharray={isCardLink ? '4 2' : undefined}
              />
            )
          })}
        </g>

        {/* 节点 */}
        <g>
          {nodesRef.current.map((n) => {
            if (n.x == null || n.y == null) return null
            const isCard = n.type === 'card'
            const isCenter = n.id === centerNodeId
            const isHover = hoverId === n.id
            const isHoverNeighbor = hoverNeighbors?.has(n.id) ?? false
            const dim = hoverNeighbors && !isHoverNeighbor
            // 外发光
            const glow = isCenter || isHover

            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                onPointerDown={(e) => handlePointerDown(e, n)}
                onPointerEnter={() => setHoverId(n.id)}
                onPointerLeave={() => setHoverId(null)}
                style={{ cursor: 'grab', opacity: dim ? 0.25 : 1 }}
              >
                {isCard ? (
                  <>
                    {/* 卡片：六边形 + 紫色 */}
                    {glow && <circle r={28} fill="#A78BFA" opacity={0.2} />}
                    <polygon
                      points="0,-22 19,-11 19,11 0,22 -19,11 -19,-11"
                      fill={isCenter ? '#A78BFA' : '#1F1B3A'}
                      stroke="#A78BFA"
                      strokeWidth={2}
                    />
                    <Layers className="h-3 w-3" strokeWidth={1.5} style={{ color: '#E0D4FF', transform: 'translate(-6px,-6px)' }} />
                  </>
                ) : (
                  <>
                    {/* 笔记：圆形 */}
                    {glow && <circle r={20} fill="#22D3EE" opacity={0.15} />}
                    <circle
                      r={isCenter ? 12 : 9}
                      fill={isCenter ? '#22D3EE' : '#1E293B'}
                      stroke={isHover ? '#22D3EE' : '#475569'}
                      strokeWidth={isCenter ? 2 : 1}
                    />
                  </>
                )}
                {/* 标签 */}
                <text
                  y={isCard ? 34 : 22}
                  textAnchor="middle"
                  className="pointer-events-none fill-starlight"
                  style={{
                    fontSize: isCard ? '11px' : '10px',
                    fontWeight: isCard ? 600 : 400,
                    textShadow: '0 1px 3px rgba(0,0,0,0.8)',
                  }}
                >
                  {(n.title || `#${n.ref_id}`).slice(0, 18)}
                  {(n.title || '').length > 18 ? '…' : ''}
                </text>
                {isCard && (
                  <text
                    y={-30}
                    textAnchor="middle"
                    className="pointer-events-none fill-flux"
                    style={{ fontSize: '8px', fontWeight: 700, letterSpacing: '0.1em' }}
                  >
                    CARD
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      {/* hover tooltip */}
      {hoverId && (() => {
        const n = nodesRef.current.find((x) => x.id === hoverId)
        if (!n) return null
        return (
          <Link
            to={n.type === 'card' ? `/cards/${n.ref_id}` : `/notes/${n.ref_id}`}
            className="absolute left-3 top-3 max-w-xs rounded-lg border border-white/10 bg-void-200/95 p-3 shadow-xl backdrop-blur"
            style={{ pointerEvents: 'auto' }}
          >
            <div className="flex items-center gap-1.5">
              {n.type === 'card' ? (
                <Layers className="h-3 w-3 text-flux" />
              ) : (
                <FileText className="h-3 w-3 text-azure" />
              )}
              <span className="text-xs font-medium text-starlight">{n.title}</span>
            </div>
            {n.subtitle && (
              <p className="mt-1 line-clamp-2 text-[10px] text-dust">{n.subtitle}</p>
            )}
            <div className="mt-1 font-mono text-[9px] text-dust/60">
              点击查看 {n.type === 'card' ? '卡片' : '笔记'}详情 →
            </div>
          </Link>
        )
      })()}

      {/* 图例 */}
      <div className="absolute bottom-3 right-3 flex items-center gap-3 rounded-lg border border-white/5 bg-void-200/80 px-3 py-2 backdrop-blur">
        <div className="flex items-center gap-1.5">
          <svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="#1E293B" stroke="#475569" /></svg>
          <span className="text-[10px] text-dust">笔记</span>
        </div>
        <div className="flex items-center gap-1.5">
          <svg width="14" height="14"><polygon points="7,1 13,4 13,10 7,13 1,10 1,4" fill="#1F1B3A" stroke="#A78BFA" strokeWidth="1.5" /></svg>
          <span className="text-[10px] text-dust">知识卡片</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-px w-4 bg-azure/60" />
          <span className="text-[10px] text-dust">note-note</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-px w-4 bg-flux/60" style={{ backgroundImage: 'linear-gradient(90deg, #A78BFA 50%, transparent 50%)', backgroundSize: '4px 1px' }} />
          <span className="text-[10px] text-dust">card-note</span>
        </div>
      </div>

      {/* 提示 */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-1.5 font-mono text-[10px] text-dust/60">
        <Maximize2 className="h-3 w-3" />
        拖拽节点 · hover 看邻居 · 点击节点跳转
      </div>
    </div>
  )
}
