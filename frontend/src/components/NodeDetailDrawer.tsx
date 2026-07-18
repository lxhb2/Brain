import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { X, ArrowRight, ExternalLink } from 'lucide-react'
import { api, type Note, type GraphData } from '@/api/client'
import { StatusBadge, shortDate } from '@/components/StatusBadge'
import { cn } from '@/lib/utils'

interface NodeDetailDrawerProps {
  noteId: number | null
  onClose: () => void
}

const LINK_TYPE_LABEL: Record<string, string> = {
  semantic: '语义',
  keyword: '关键词',
  temporal: '时间',
}

export default function NodeDetailDrawer({ noteId, onClose }: NodeDetailDrawerProps) {
  const navigate = useNavigate()
  const [note, setNote] = useState<Note | null>(null)
  const [neighbors, setNeighbors] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (noteId == null) {
      setNote(null)
      setNeighbors(null)
      return
    }
    setLoading(true)
    Promise.all([api.getNote(noteId), api.getNeighbors(noteId)])
      .then(([n, nb]) => {
        setNote(n)
        setNeighbors(nb)
      })
      .finally(() => setLoading(false))
  }, [noteId])

  if (noteId == null) return null

  return (
    <div className="absolute inset-0 z-30 flex h-full flex-col bg-void-300/95 backdrop-blur-xl animate-fade-in md:inset-auto md:right-0 md:top-0 md:w-80 md:border-l md:border-white/5 md:bg-void-300/80">
      {/* 头部 */}
      <div className="safe-top flex items-center justify-between border-b border-white/5 px-4 py-4">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust">节点详情</span>
        <button onClick={onClose} className="btn-ghost p-1.5">
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="space-y-3 p-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-white/5" />
          ))}
        </div>
      ) : note ? (
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {/* 缩略图 */}
          <div className="overflow-hidden rounded-lg border border-white/10 bg-void-500/40">
            <img src={api.noteThumbnailUrl(note.id)} alt={note.title ?? ''} className="h-40 w-full object-cover" />
          </div>

          {/* 标题 */}
          <div>
            <h2 className="font-display text-lg leading-snug text-starlight">{note.title ?? '(未命名)'}</h2>
            <div className="mt-1.5 flex items-center gap-3">
              <StatusBadge status={note.status} />
              <span className="font-mono text-[11px] text-dust">{shortDate(note.created_at)}</span>
            </div>
          </div>

          {/* 来源 */}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
              <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">设备</div>
              <div className="text-sm text-starlight">{note.source_device ?? '—'}</div>
            </div>
            <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
              <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">应用</div>
              <div className="text-sm text-starlight">{note.source_app ?? '—'}</div>
            </div>
          </div>

          {/* 摘要 */}
          {note.summary && (
            <div>
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-dust/70">摘要</div>
              <p className="text-sm leading-relaxed text-starlight/80">{note.summary}</p>
            </div>
          )}

          {/* 关键词 */}
          {note.keywords && note.keywords.length > 0 && (
            <div>
              <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-dust/70">关键词</div>
              <div className="flex flex-wrap gap-1.5">
                {note.keywords.map((kw) => (
                  <span key={kw} className="chip">{kw}</span>
                ))}
              </div>
            </div>
          )}

          {/* 关联笔记 */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-wider text-dust/70">
                关联笔记 ({neighbors?.nodes.length ?? 0})
              </span>
            </div>
            <div className="space-y-2">
              {neighbors?.nodes.map((nb) => {
                const edge = neighbors.edges.find(
                  (e) => (e.source === note.id && e.target === nb.id) || (e.target === note.id && e.source === nb.id),
                )
                return (
                  <button
                    key={nb.id}
                    onClick={() => navigate('/notes/' + nb.id)}
                    className="group flex w-full items-center gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-left transition-all hover:border-azure/30 hover:bg-azure/5"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-starlight">{nb.title}</div>
                      <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-dust">
                        <span>{nb.source_device ?? '—'}</span>
                        {edge?.link_type && (
                          <span className={cn('rounded px-1 py-0.5', 'bg-white/5 text-azure')}>
                            {LINK_TYPE_LABEL[edge.link_type] ?? edge.link_type}
                          </span>
                        )}
                        {edge && <span className="text-dust/60">· {edge.weight.toFixed(2)}</span>}
                      </div>
                    </div>
                    <ArrowRight className="h-3.5 w-3.5 text-dust transition-colors group-hover:text-azure" />
                  </button>
                )
              })}
              {neighbors && neighbors.nodes.length === 0 && (
                <div className="rounded-lg border border-dashed border-white/5 px-3 py-4 text-center font-mono text-xs text-dust/50">
                  暂无关联笔记
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 text-sm text-dust">加载失败</div>
      )}

      {/* 底部跳转 */}
      {note && (
        <div className="border-t border-white/5 p-4">
          <button
            onClick={() => navigate('/notes/' + note.id)}
            className="btn-ghost w-full justify-center"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            查看完整笔记
          </button>
        </div>
      )}
    </div>
  )
}
