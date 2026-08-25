import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  DatabaseBackup,
  RefreshCw,
  ScrollText,
  Upload,
} from 'lucide-react'
import { api, type ActivityLog } from '@/api/client'
import { cn } from '@/lib/utils'

const filters = [
  { key: '', label: '全部' },
  { key: 'model', label: '模型' },
  { key: 'upload', label: '上传' },
  { key: 'backup', label: '备份' },
  { key: 'error', label: '错误' },
] as const

function EventIcon({ type }: { type: ActivityLog['event_type'] }) {
  if (type === 'model') return <Bot className="h-4 w-4 text-flux" strokeWidth={1.5} />
  if (type === 'upload') return <Upload className="h-4 w-4 text-azure" strokeWidth={1.5} />
  if (type === 'backup') return <DatabaseBackup className="h-4 w-4 text-starlight" strokeWidth={1.5} />
  if (type === 'error') return <AlertTriangle className="h-4 w-4 text-amber" strokeWidth={1.5} />
  return <ScrollText className="h-4 w-4 text-dust" strokeWidth={1.5} />
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export default function Logs() {
  const [logs, setLogs] = useState<ActivityLog[]>([])
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [backingUp, setBackingUp] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await api.listActivityLogs({ event_type: filter || undefined, limit: 100 })
      setLogs(data.items)
      setTotal(data.total)
      setError('')
    } catch {
      setError('日志加载失败')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  useEffect(() => {
    const timer = window.setInterval(load, 15000)
    return () => window.clearInterval(timer)
  }, [load])

  const backup = async () => {
    setBackingUp(true)
    setNotice('')
    try {
      const result = await api.createBackup()
      setNotice(`已备份：${result.file_name}`)
      await load()
    } catch {
      setNotice('备份失败')
    } finally {
      setBackingUp(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="safe-top border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="flex items-center gap-2.5">
          <ScrollText className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-lg text-starlight md:text-xl">活动日志</h1>
        </div>
        <p className="mt-1 text-xs text-dust md:text-sm">模型任务、文件上传与自动备份记录</p>
      </div>

      <div className="border-b border-white/5 px-4 py-3 md:px-8">
        <div className="mx-auto flex max-w-4xl items-center gap-2 overflow-x-auto">
          {filters.map((item) => (
            <button
              key={item.key || 'all'}
              onClick={() => setFilter(item.key)}
              className={cn(
                'shrink-0 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                filter === item.key
                  ? 'border-flux/25 bg-flux/10 text-flux'
                  : 'border-white/5 bg-white/[0.02] text-dust hover:text-starlight',
              )}
            >
              {item.label}
            </button>
          ))}
          <span className="ml-auto hidden shrink-0 font-mono text-[11px] text-dust md:block">{total} 条</span>
          <button onClick={() => load()} className="btn-ghost h-8 w-8 justify-center p-0" aria-label="刷新">
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </button>
          <button onClick={backup} disabled={backingUp} className="btn-primary h-8 px-3 text-xs" aria-label="立即备份">
            <DatabaseBackup className="h-3.5 w-3.5" />
            备份
          </button>
        </div>
        {notice ? <div className="mx-auto mt-2 max-w-4xl text-xs text-flux">{notice}</div> : null}
        {error ? <div className="mx-auto mt-2 max-w-4xl text-xs text-amber">{error}</div> : null}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-6">
        <div className="mx-auto max-w-4xl space-y-2">
          {!loading && !logs.length ? (
            <div className="glass-panel rounded-xl p-8 text-center text-sm text-dust">暂无活动记录</div>
          ) : null}
          {logs.map((log) => (
            <article key={log.id} className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 shrink-0"><EventIcon type={log.event_type} /></span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-sm leading-relaxed text-starlight">{log.message}</p>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-dust">
                    <span>{formatTime(log.created_at)}</span>
                    {log.device ? <span>{log.device}-{log.app || 'unknown'}</span> : null}
                    {log.note_id ? <span>#{log.note_id}</span> : null}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}
