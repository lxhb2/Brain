import { memo } from 'react'
import { Handle, Position, type NodeProps } from 'reactflow'
import { cn } from '@/lib/utils'
import { type GraphNode } from '@/api/client'

export interface NoteNodeData extends GraphNode {
  isNeighbor?: boolean
  degree?: number
}

// 设备颜色映射（Obsidian 风格：不同分组不同颜色）
export const DEVICE_COLOR: Record<string, string> = {
  ipad: '#22D3EE',
  android: '#34D399',
  pc: '#A78BFA',
  camera: '#F5A623',
  unknown: '#6EA8FE',
}

export function colorForDevice(device: string | null): string {
  if (!device) return DEVICE_COLOR.unknown
  return DEVICE_COLOR[device.toLowerCase()] ?? DEVICE_COLOR.unknown
}

function NoteNodeBase({ data, selected }: NodeProps<NoteNodeData>) {
  const note = data
  const degree = note.degree ?? 0
  const color = colorForDevice(note.source_device)
  // 节点大小：连接越多越大，8 ~ 28px（Obsidian 星图风格）
  const size = Math.min(28, 8 + degree * 2.4)
  const isFailed = note.status === 'failed'

  return (
    <div
      className="group relative flex cursor-grab items-center justify-center active:cursor-grabbing"
      style={{ width: size, height: size }}
    >
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />

      {/* 圆点本体 */}
      <div
        className={cn(
          'rounded-full transition-transform duration-200',
          selected ? 'scale-125' : 'group-hover:scale-110',
        )}
        style={{
          width: size,
          height: size,
          background: color,
          boxShadow: selected
            ? `0 0 0 3px rgba(245,166,35,0.45), 0 0 18px ${color}`
            : `0 0 8px ${color}80`,
          border: isFailed ? '2px solid #EF4444' : 'none',
        }}
      />

      {/* 选中光环 */}
      {selected && (
        <div
          className="pointer-events-none absolute rounded-full border border-amber/40 animate-pulse-slow"
          style={{ inset: -6 }}
        />
      )}

      {/* hover / 选中 标题气泡 */}
      <div
        className={cn(
          'pointer-events-none absolute left-1/2 top-full z-20 mt-2 -translate-x-1/2 max-w-[180px] truncate rounded-md border border-white/10 bg-void-300/95 px-2 py-1 font-mono text-[10px] text-starlight shadow-lg backdrop-blur-md transition-opacity duration-150',
          selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
        )}
      >
        {note.title}
      </div>
    </div>
  )
}

export const NoteNode = memo(NoteNodeBase)
