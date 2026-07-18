import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, NotebookPen, ChevronRight } from 'lucide-react'
import { api, type Note, type NoteStatus, type NotesListResponse } from '@/api/client'
import { StatusBadge, shortDate } from '@/components/StatusBadge'
import { cn } from '@/lib/utils'

const STATUS_TABS: { value: NoteStatus | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'done', label: '已完成' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: 'OCR中' },
  { value: 'failed', label: '失败' },
]

export default function Notes() {
  const [data, setData] = useState<NotesListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<NoteStatus | ''>('')
  const [device, setDevice] = useState('')

  const fetchNotes = useCallback(() => {
    setLoading(true)
    api
      .listNotes({ q, status: status || undefined, device: device || undefined, limit: 60, offset: 0 })
      .then(setData)
      .finally(() => setLoading(false))
  }, [q, status, device])

  useEffect(() => {
    const t = setTimeout(fetchNotes, q ? 300 : 0)
    return () => clearTimeout(t)
  }, [fetchNotes])

  const devices = useMemo(
    () => Array.from(new Set((data?.items ?? []).map((n) => n.source_device).filter(Boolean) as string[])),
    [data],
  )

  return (
    <div className="flex h-full flex-col">
      {/* 顶部 */}
      <div className="border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <NotebookPen className="h-4 w-4 text-flux" strokeWidth={1.5} />
            <h1 className="font-display text-lg text-starlight md:text-xl">笔记浏览</h1>
          </div>
          <div className="font-mono text-xs text-dust">{data?.total ?? 0} 条</div>
        </div>

        {/* 筛选条 */}
        <div className="mt-3 flex flex-wrap items-center gap-2 md:gap-3">
          <div className="relative w-full md:w-64">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dust" strokeWidth={1.5} />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索标题 / OCR / 摘要…"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 py-2.5 pl-8 pr-3 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
          <div className="flex flex-1 items-center gap-1.5 overflow-x-auto">
            {STATUS_TABS.map((t) => (
              <button
                key={t.value}
                onClick={() => setStatus(t.value)}
                className={cn('chip shrink-0', status === t.value && 'chip-active')}
              >
                {t.label}
              </button>
            ))}
            {devices.length > 0 && (
              <select
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                className="ml-auto rounded-lg border border-white/10 bg-void-500/40 px-2 py-1.5 text-sm text-starlight focus:border-flux/40 focus:outline-none"
              >
                <option value="">全部设备</option>
                {devices.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            )}
          </div>
        </div>
      </div>

      {/* 网格 */}
      <div className="flex-1 overflow-y-auto px-4 py-4 md:px-8 md:py-6">
        {loading ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 md:gap-4">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-44 animate-pulse rounded-xl border border-white/5 bg-white/[0.02] md:h-52" />
            ))}
          </div>
        ) : data && data.items.length > 0 ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 md:gap-4">
            {data.items.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-dust">
            <NotebookPen className="h-10 w-10 opacity-40" strokeWidth={1} />
            <div className="font-display text-lg text-starlight/70">暂无笔记</div>
            <p className="max-w-xs text-sm">
              将笔记文件放入 <code className="rounded bg-white/5 px-1 font-mono text-xs">synced_notes/</code> 目录，等待自动入库。
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function NoteCard({ note }: { note: Note }) {
  return (
    <Link
      to={`/notes/${note.id}`}
      className="group relative flex flex-col overflow-hidden rounded-xl border border-white/5 bg-void-200/40 transition-all hover:border-azure/30 hover:shadow-glow"
    >
      {/* 缩略图 */}
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-void-500/40">
        <img
          src={api.noteThumbnailUrl(note.id)}
          alt={note.title ?? ''}
          loading="lazy"
          className="h-full w-full object-cover opacity-80 transition-all duration-300 group-hover:scale-105 group-hover:opacity-100"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-void-200/80 via-transparent to-transparent" />
        <div className="absolute right-2 top-2 rounded-md bg-void-500/70 px-1.5 py-0.5 backdrop-blur-sm">
          <StatusBadge status={note.status} />
        </div>
      </div>

      {/* 信息 */}
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="line-clamp-2 font-display text-sm leading-snug text-starlight">{note.title ?? '(未命名)'}</div>
        <div className="mt-auto flex items-center justify-between font-mono text-[10px] text-dust">
          <span className="truncate">{note.source_device ?? '—'}</span>
          <span>{shortDate(note.created_at)}</span>
        </div>
      </div>

      <div className="absolute right-3 bottom-3 flex h-6 w-6 translate-y-1 items-center justify-center rounded-full bg-flux/15 text-flux opacity-0 transition-all group-hover:translate-y-0 group-hover:opacity-100">
        <ChevronRight className="h-3.5 w-3.5" />
      </div>
    </Link>
  )
}
