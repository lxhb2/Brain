import { useEffect, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Layers, FileText, Sparkles, Trash2, Loader2,
  BookOpen, Lightbulb, Target, HelpCircle, CheckCircle2
} from 'lucide-react'
import { api, type KnowledgeCard } from '@/api/client'
import { shortDate } from '@/components/StatusBadge'

export default function CardDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [card, setCard] = useState<KnowledgeCard | null>(null)
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    api.getCard(Number(id))
      .then(setCard)
      .catch(() => setCard(null))
      .finally(() => setLoading(false))
  }, [id])

  const handleDelete = async () => {
    if (!card) return
    if (!confirm('删除这张知识卡片？关联的链接也会被清理。')) return
    setDeleting(true)
    try {
      await api.deleteCard(card.id)
      navigate('/cards')
    } catch (e) {
      alert(`删除失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-flux/60" />
      </div>
    )
  }

  if (!card) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-dust">
        <p>卡片不存在</p>
        <Link to="/cards" className="btn-ghost">返回列表</Link>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部栏 */}
      <div className="safe-top flex items-center justify-between gap-2 border-b border-white/5 px-4 py-3 md:px-8 md:py-4">
        <div className="flex min-w-0 items-center gap-2">
          <Link to="/cards" className="btn-ghost px-2 py-1.5">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate font-display text-base text-starlight md:text-lg">
              {card.title}
            </h1>
            <div className="font-mono text-[10px] text-dust/60">
              #{card.id} · {shortDate(card.created_at)}
              {card.session_id && ` · 会话 ${card.session_id.slice(0, 12)}`}
            </div>
          </div>
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="btn-ghost px-2 py-1.5 text-rose hover:bg-rose/10"
          title="删除卡片"
        >
          {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-8">
        <div className="mx-auto max-w-3xl space-y-4">
          {/* 核心讲了什么 */}
          <section className="rounded-xl border border-white/5 bg-white/[0.02] p-4 md:p-5">
            <div className="mb-2 flex items-center gap-2">
              <BookOpen className="h-4 w-4 text-flux/80" strokeWidth={1.5} />
              <h2 className="font-display text-sm text-starlight">核心讲了什么</h2>
            </div>
            <p className="text-sm leading-relaxed text-starlight/90 whitespace-pre-wrap">
              {card.core_summary}
            </p>
          </section>

          {/* 关键结论 */}
          <section className="rounded-xl border border-azure/20 bg-azure/[0.04] p-4 md:p-5">
            <div className="mb-2 flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-azure/80" strokeWidth={1.5} />
              <h2 className="font-display text-sm text-starlight">关键结论（需要记住的）</h2>
            </div>
            <p className="text-sm leading-relaxed text-starlight/90 whitespace-pre-wrap">
              {card.key_conclusion}
            </p>
          </section>

          {/* 落地场景 */}
          {card.application_scenario && (
            <section className="rounded-xl border border-amber/20 bg-amber/[0.04] p-4 md:p-5">
              <div className="mb-2 flex items-center gap-2">
                <Target className="h-4 w-4 text-amber/80" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">落地使用场景</h2>
              </div>
              <p className="text-sm leading-relaxed text-starlight/90 whitespace-pre-wrap">
                {card.application_scenario}
              </p>
            </section>
          )}

          {/* Agent 提问 + 用户回答 + AI 补充 */}
          {card.agent_question && (
            <section className="rounded-xl border border-flux/20 bg-flux/[0.03] p-4 md:p-5">
              <div className="mb-2 flex items-center gap-2">
                <HelpCircle className="h-4 w-4 text-flux/80" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">Agent 检验性提问</h2>
              </div>
              <p className="text-sm text-starlight/90 whitespace-pre-wrap">
                {card.agent_question}
              </p>

              {/* 用户回答 */}
              <div className="mt-3 border-t border-white/5 pt-3">
                <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-dust/60">
                  你的回答
                </div>
                {card.user_answer ? (
                  <p className="text-sm text-starlight/90 whitespace-pre-wrap">
                    {card.user_answer}
                  </p>
                ) : (
                  <p className="text-sm italic text-dust/50">（跳过）</p>
                )}
              </div>

              {/* AI 补充 */}
              {card.ai_supplement && (
                <div className="mt-3 border-t border-white/5 pt-3">
                  <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-amber">
                    <Sparkles className="h-3 w-3" />
                    AI 补充
                  </div>
                  <p className="text-sm leading-relaxed text-starlight/90 whitespace-pre-wrap">
                    {card.ai_supplement}
                  </p>
                </div>
              )}
            </section>
          )}

          {/* 关联笔记 */}
          {card.source_note_ids.length > 0 && (
            <section className="rounded-xl border border-white/5 bg-white/[0.02] p-4 md:p-5">
              <div className="mb-2 flex items-center gap-2">
                <FileText className="h-4 w-4 text-dust/80" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">关联笔记</h2>
                <span className="font-mono text-[10px] text-dust/50">
                  共 {card.source_note_ids.length} 篇
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {card.source_note_ids.map((nid) => (
                  <Link
                    key={nid}
                    to={`/notes/${nid}`}
                    className="group flex items-center gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 transition-all hover:border-azure/30 hover:bg-azure/5"
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0 text-dust group-hover:text-azure" strokeWidth={1.5} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-starlight">笔记 #{nid}</div>
                      <div className="font-mono text-[10px] text-dust/50">点击查看原文</div>
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* 图谱链接入口 */}
          <section className="rounded-xl border border-flux/20 bg-flux/[0.03] p-4 md:p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-flux/80" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">在图谱中查看</h2>
              </div>
              <Link
                to={`/graph?center=card:${card.id}`}
                className="btn-ghost flex items-center gap-1.5 px-3 py-1.5 text-xs"
              >
                <CheckCircle2 className="h-3 w-3" />
                打开图谱（以此卡片为中心）
              </Link>
            </div>
            <p className="mt-2 text-[11px] text-dust/70">
              在图谱中可看到这张卡片如何连接到引用的笔记，以及相关卡片
            </p>
          </section>

          {/* 元信息 */}
          <div className="border-t border-white/5 pt-4 text-center font-mono text-[10px] text-dust/50">
            创建于 {shortDate(card.created_at)} · 更新于 {shortDate(card.updated_at)}
            {card.qa_id && ` · 源自问答 #${card.qa_id}`}
          </div>
        </div>
      </div>
    </div>
  )
}
