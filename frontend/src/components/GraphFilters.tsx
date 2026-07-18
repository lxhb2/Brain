import { Search, RotateCcw, Filter, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface GraphFiltersState {
  device: string
  app: string
  status: string
  q: string
}

interface GraphFiltersProps {
  state: GraphFiltersState
  onChange: (state: GraphFiltersState) => void
  devices: string[]
  apps: string[]
  nodeCount: number
  edgeCount: number
  /** 移动端 Sheet 模式：传入 onClose 显示关闭按钮 */
  onClose?: () => void
}

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'done', label: '已完成' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: 'OCR中' },
  { value: 'failed', label: '失败' },
]

export default function GraphFilters({ state, onChange, devices, apps, nodeCount, edgeCount, onClose }: GraphFiltersProps) {
  const update = (patch: Partial<GraphFiltersState>) => onChange({ ...state, ...patch })
  const reset = () => onChange({ device: '', app: '', status: '', q: '' })
  const activeCount = [state.device, state.app, state.status, state.q].filter(Boolean).length

  return (
    <div className="flex h-full w-full flex-col bg-void-300/80 backdrop-blur-xl md:w-64 md:border-r md:border-white/5 md:bg-void-300/40">
      <div className="flex items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2 text-dust">
          <Filter className="h-3.5 w-3.5" strokeWidth={1.5} />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em]">筛选</span>
          {activeCount > 0 && (
            <span className="rounded-full bg-flux/15 px-1.5 py-0.5 font-mono text-[9px] text-flux">{activeCount}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={reset} className="btn-ghost px-2 py-1 text-xs">
            <RotateCcw className="h-3 w-3" />
            重置
          </button>
          {onClose && (
            <button onClick={onClose} className="btn-ghost p-1.5 md:hidden">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 pb-4">
        {/* 关键词搜索 */}
        <div>
          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-dust/70">关键词</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dust" strokeWidth={1.5} />
            <input
              value={state.q}
              onChange={(e) => update({ q: e.target.value })}
              placeholder="搜索标题 / 摘要…"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 py-2.5 pl-8 pr-3 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
        </div>

        {/* 来源设备 */}
        <div>
          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-dust/70">来源设备</label>
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => update({ device: '' })}
              className={cn('chip', !state.device && 'chip-active')}
            >
              全部
            </button>
            {devices.map((d) => (
              <button key={d} onClick={() => update({ device: d })} className={cn('chip', state.device === d && 'chip-active')}>
                {d}
              </button>
            ))}
          </div>
        </div>

        {/* 来源 App */}
        <div>
          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-dust/70">来源应用</label>
          <div className="flex flex-wrap gap-1.5">
            <button onClick={() => update({ app: '' })} className={cn('chip', !state.app && 'chip-active')}>
              全部
            </button>
            {apps.map((a) => (
              <button key={a} onClick={() => update({ app: a })} className={cn('chip', state.app === a && 'chip-active')}>
                {a}
              </button>
            ))}
          </div>
        </div>

        {/* 状态 */}
        <div>
          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-dust/70">处理状态</label>
          <div className="flex flex-wrap gap-1.5">
            {STATUS_OPTIONS.map((s) => (
              <button key={s.value} onClick={() => update({ status: s.value })} className={cn('chip', state.status === s.value && 'chip-active')}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 计数 */}
      <div className="safe-bottom border-t border-white/5 px-4 py-3">
        <div className="flex items-center justify-between font-mono text-[11px]">
          <span className="text-dust">节点 / 边</span>
          <span className="tabular-nums text-starlight">
            {nodeCount} <span className="text-dust/40">/</span> {edgeCount}
          </span>
        </div>
      </div>
    </div>
  )
}
