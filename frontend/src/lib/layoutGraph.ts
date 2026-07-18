// 轻量级力导向布局 —— 纯 TS 实现，无额外依赖。
// 适合几百节点的知识星座可视化：节点间排斥 + 边吸引 + 中心引力。

export interface LayoutNode {
  id: number
  x: number
  y: number
}

export interface LayoutInput {
  nodeIds: number[]
  edges: { source: number; target: number; weight: number }[]
  width: number
  height: number
  iterations?: number
}

/**
 * 计算力导向布局。返回 id -> {x, y} 映射。
 * 使用黄金角初始分布，保证每次结果稳定且形似星座。
 *
 * 调参要点（让网络像星图一样充分展开而非缩成一团）：
 *  - 排斥力要足够大，把无连接的节点互相推开
 *  - 中心引力要弱，只在边缘起收敛作用，不把节点拽向中心
 *  - 边的吸引力按权重调节理想距离，连接越紧密靠得越近，但不重叠
 */
export function computeLayout(input: LayoutInput): Map<number, LayoutNode> {
  const { nodeIds, edges, width, height, iterations = 220 } = input
  const n = nodeIds.length
  const positions = new Map<number, LayoutNode>()

  if (n === 0) return positions

  const cx = width / 2
  const cy = height / 2
  // 用较大的半径初始化，让节点一开始就散开
  const radius = Math.min(width, height) * 0.42

  // 黄金角初始分布（向日葵）
  const golden = Math.PI * (3 - Math.sqrt(5))
  nodeIds.forEach((id, i) => {
    const r = radius * Math.sqrt((i + 0.5) / n)
    const theta = i * golden
    positions.set(id, {
      id,
      x: cx + r * Math.cos(theta),
      y: cy + r * Math.sin(theta),
    })
  })

  if (n <= 1) return positions

  // 邻接表（权重越高吸引力越强）
  const adj = new Map<number, number[]>()
  nodeIds.forEach((id) => adj.set(id, []))
  edges.forEach((e) => {
    if (positions.has(e.source) && positions.has(e.target)) {
      adj.get(e.source)!.push(e.target)
      adj.get(e.target)!.push(e.source)
    }
  })

  // 理想节点间距：根据节点数与画布尺寸自适应，保证充分展开
  // 圆点节点比卡片小，间距下限更紧凑，呈 Obsidian 星图风格
  const area = width * height
  const k = Math.max(60, Math.sqrt(area / Math.max(n, 1)) * 0.45) // 理想距离
  // 排斥力强度：大幅提高，把节点互相推开
  const repulsion = k * k * 6.0
  // 边吸引力基准：偏弱，让排斥力主导展开
  const attractBase = 0.05
  // 中心引力：很弱，只在远离中心时起轻微收敛作用
  const center = 0.003

  // 用「温度」模拟退火：前期允许大位移展开，后期收敛稳定
  let temperature = radius * 0.5
  const minTemp = 1.0
  const cooling = 0.985

  for (let iter = 0; iter < iterations; iter++) {
    const forces = new Map<number, { x: number; y: number }>()
    nodeIds.forEach((id) => forces.set(id, { x: 0, y: 0 }))

    // 排斥力（O(n^2)，n 较小时可接受）
    for (let i = 0; i < n; i++) {
      const a = positions.get(nodeIds[i])!
      for (let j = i + 1; j < n; j++) {
        const b = positions.get(nodeIds[j])!
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dist2 = dx * dx + dy * dy
        if (dist2 < 0.01) {
          dx = (Math.random() - 0.5) * 0.5
          dy = (Math.random() - 0.5) * 0.5
          dist2 = 0.25
        }
        const dist = Math.sqrt(dist2)
        const force = repulsion / dist2
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        forces.get(nodeIds[i])!.x += fx
        forces.get(nodeIds[i])!.y += fy
        forces.get(nodeIds[j])!.x -= fx
        forces.get(nodeIds[j])!.y -= fy
      }
    }

    // 边吸引力
    edges.forEach((e) => {
      if (!positions.has(e.source) || !positions.has(e.target)) return
      const a = positions.get(e.source)!
      const b = positions.get(e.target)!
      const dx = a.x - b.x
      const dy = a.y - b.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01
      // 权重越高，期望距离越短（但不会比 k*0.6 更近，避免重叠）
      const ideal = k * Math.max(0.6, 1.5 - Math.min(0.9, e.weight * 0.9))
      const force = (dist - ideal) * attractBase
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      forces.get(e.source)!.x -= fx
      forces.get(e.source)!.y -= fy
      forces.get(e.target)!.x += fx
      forces.get(e.target)!.y += fy
    })

    // 中心引力 + 应用位移（受温度限制）
    nodeIds.forEach((id) => {
      const p = positions.get(id)!
      const f = forces.get(id)!
      f.x += (cx - p.x) * center
      f.y += (cy - p.y) * center
      // 限制单次位移不超过当前温度，防止后期震荡
      const fmag = Math.sqrt(f.x * f.x + f.y * f.y)
      const step = fmag > temperature ? temperature / fmag : 1
      p.x += f.x * step
      p.y += f.y * step
    })

    // 退火降温
    temperature = Math.max(minTemp, temperature * cooling)
  }

  return positions
}
