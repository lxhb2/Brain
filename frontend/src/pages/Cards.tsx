import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Layers, FileText, Sparkles, ArrowRight, Trash2, Loader2, Inbox } from 'lucide-react'
import { api, type KnowledgeCard } from '@/api/client'
import { shortDate } from '@/components/StatusBadge'

export default function Cards() {
  const [items, setItems] = useState<KnowledgeCard[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  useEffect(() => {
    api.listCards(100, 0)
      .then((res) => {
        setItems(res.items)
        setTotal(res.total)
      })
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = async (id: number) => {
    if (!confirm('删除这张知识卡片？关联的链接也会被清理。')) return
    setDeletingId(id)
    try {
      await api.deleteCard(id)
      setItems((arr) => arr.filter((c) => c.id !== id))
      setTotal((n) => n - 1)
    } catch (e) {
      alert(`删除失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部 */}
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-3 md:px-8 md:py-4">
        <div className="flex items-center gap-2.5">
          <Layers className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-base text-starlight md:text-xl">知识卡片</h1>
          <span className="hidden font-mono text-[10px] text-dust/60 md:inline">
            · 每次问答沉淀的结构化知识
          </span>
        </div>
        <div className="font-mono text-[11px] text-dust/70">
          共 {total} 张
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-8">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-flux/60" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-dust">
            <Inbox className="h-10 w-10 opacity-50" strokeWidth={1.2} />
            <p className="text-sm">还没有知识卡片</p>
            <p className="max-w-xs text-center text-[11px] text-dust/60">
              去问 Agent 一些问题，每次有引用笔记的回答都会生成卡片草稿，存档后会出现在这里
            </p>
            <Link to="/qa" className="btn-ghost mt-2 px-3 py-1.5 text-xs">
              <Sparkles className="mr-1 inline h-3 w-3" />
              去问答
            </Link>
          </div>
        ) : (
          <div className="mx-auto grid max-w-5xl gap-3 md:grid-cols-2">
            {items.map((c) => (
              <div
                key={c.id}
                className="group relative rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-all hover:border-flux/30 hover:bg-flux/[0.03]"
              >
                {/* 标题 */}
                <div className="flex items-start gap-2">
                  <Layers className="mt-0.5 h-4 w-4 shrink-0 text-flux/70" strokeWidth={1.5} />
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/cards/${c.id}`}
                      className="font-display text-sm text-starlight hover:text-flux"
                    >
                      {c.title}
                    </Link>
                    <div className="mt-0.5 font-mono text-[10px] text-dust/50">
                      #{c.id} · {shortDate(c.created_at)}
                    </div>
                  </div>
                  <button
                    onClick={() => handleDelete(c.id)}
                    disabled={deletingId === c.id}
                    className="shrink-0 text-dust opacity-0 transition-opacity hover:text-rose group-hover:opacity-100"
                    title="删除"
                  >
                    {deletingId === c.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                  </button>
                </div>

                {/* 核心总结 */}
                <p className="mt-2 line-clamp-2 text-xs text-starlight/80">
                  {c.core_summary}
                </p>

                {/* 关键结论 */}
                <div className="mt-2 rounded-md bg-azure/5 px-2 py-1.5">
                  <div className="font-mono text-[9px] uppercase tracking-wider text-azure/60">关键结论</div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-starlight/80">
                    {c.key_conclusion}
                  </p>
                </div>

                {/* 关联笔记 */}
                {c.source_note_ids.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    <FileText className="h-3 w-3 text-dust/60" />
                    {c.source_note_ids.slice(0, 5).map((nid) => (
                      <Link
                        key={nid}
                        to={`/notes/${nid}`}
                        className="rounded border border-white/10 bg-white/5 px-1 py-0 text-[9px] text-dust hover:border-azure/30 hover:text-azure"
                      >
                        #{nid}
                      </Link>
                    ))}
                    {c.source_note_ids.length > 5 && (
                      <span className="text-[9px] text-dust/50">
                        +{c.source_note_ids.length - 5}
                      </span>
                    )}
                  </div>
                )}

                {/* AI 补充标记 */}
                {c.ai_supplement && (
                  <div className="mt-2 flex items-center gap-1 font-mono text-[10px] text-amber/80">
                    <Sparkles className="h-2.5 w-2.5" />
                    含 AI 补充
                  </div>
                )}

                {/* 查看详情 */}
                <Link
                  to={`/cards/${c.id}`}
                  className="mt-3 flex items-center justify-end gap-1 text-[11px] text-dust/70 hover:text-flux"
                >
                  查看详情
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
