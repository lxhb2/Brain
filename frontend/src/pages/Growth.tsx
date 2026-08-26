import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Compass,
  RefreshCw,
  Target,
} from 'lucide-react'
import { api, type GrowthReview, type KnowledgeCardReview } from '@/api/client'
import { useAppStore } from '@/store'

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-dust">{label}</div>
      <div className="mt-1 font-mono text-lg tabular-nums text-starlight">{Math.round(value * 100)}%</div>
    </div>
  )
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 text-starlight">
      {icon}
      <h2 className="font-display text-base">{title}</h2>
    </div>
  )
}

export default function Growth() {
  const { stats, refresh } = useAppStore()
  const [review, setReview] = useState<GrowthReview | null>(null)
  const [dueCards, setDueCards] = useState<KnowledgeCardReview[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [cards, indexes] = await Promise.all([api.getDueCards(12), api.listGrowthReviews(7)])
    setDueCards(cards.items)
    if (indexes.reviews.length > 0) {
      setReview(await api.getGrowthReview(indexes.reviews[0].review_date))
    }
  }, [])

  useEffect(() => {
    load().catch(() => setNotice('成长数据加载失败'))
  }, [load])

  const run = async (kind: 'triage' | 'review') => {
    setBusy(true)
    try {
      if (kind === 'triage') {
        setNotice('正在分诊')
        const result = await api.runGrowthTriage(3)
        setNotice(`已分诊 ${result.triaged}/${result.found} 条笔记`)
      } else {
        setNotice('正在生成审核')
        const result = await api.runGrowthReview()
        setNotice(result.generated ? '成长审核已生成' : result.reason || '暂无可审核内容')
        await load()
      }
      await refresh()
    } catch {
      setNotice('任务执行失败')
    } finally {
      setBusy(false)
    }
  }

  const growth = stats?.growth

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="safe-top border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Compass className="h-4 w-4 text-flux" strokeWidth={1.5} />
              <h1 className="font-display text-lg text-starlight md:text-xl">成长</h1>
            </div>
            <p className="mt-1 text-xs text-dust md:text-sm">知识密度 · 调用频次 · 验证深度</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <button onClick={() => run('triage')} disabled={busy} className="btn-ghost px-3 py-1.5">
              <RefreshCw className={busy ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'} strokeWidth={1.5} />
              分诊
            </button>
            <button onClick={() => run('review')} disabled={busy} className="btn-primary px-3 py-1.5">审核今天</button>
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-5 md:px-8">
        {notice && (
          <div className="rounded-lg border border-flux/15 bg-flux/5 px-3 py-2 text-sm text-flux">{notice}</div>
        )}

        {growth && (
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="知识密度" value={growth.knowledge_density} />
            <Metric label="调用广度" value={growth.call_frequency} />
            <Metric label="验证深度" value={growth.validation_depth} />
            <Metric label="待复验比例" value={Math.min(1, growth.due_cards / Math.max(1, growth.cards_total))} />
          </section>
        )}

        <section className="space-y-3">
          <SectionTitle icon={<Target className="h-4 w-4 text-flux" strokeWidth={1.5} />} title="复验队列" />
          {dueCards.length === 0 ? (
            <div className="text-sm text-dust">当前没有到期卡片。</div>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {dueCards.map((card) => (
                <Link
                  key={card.id}
                  to={`/cards/${card.id}`}
                  className="group rounded-lg border border-white/5 bg-white/[0.02] p-3 transition-colors hover:border-flux/20 hover:bg-flux/5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm text-starlight">{card.title}</span>
                    <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 font-mono text-[10px] uppercase text-dust">
                      {card.mastery_level || 'novice'}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-dust">{card.agent_question || card.key_conclusion}</div>
                </Link>
              ))}
            </div>
          )}
        </section>

        {review ? (
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <SectionTitle icon={<Compass className="h-4 w-4 text-azure" strokeWidth={1.5} />} title={`${review.review_date} 审核`} />
              <span className="font-mono text-[11px] text-dust">{review.model}</span>
            </div>
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4 text-sm text-starlight">
              {review.content.headline || '本次审核没有给出结论。'}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <SectionTitle icon={<CheckCircle2 className="h-4 w-4 text-flux" strokeWidth={1.5} />} title="已沉淀" />
                {(review.content.kept || []).slice(0, 5).map((item, index) => (
                  <div key={index} className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                    <div className="text-sm text-starlight">{item.title}</div>
                    <div className="mt-1 text-xs text-dust">{item.why}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-2">
                <SectionTitle icon={<AlertTriangle className="h-4 w-4 text-amber" strokeWidth={1.5} />} title="错题本" />
                {(review.content.mistakes || []).slice(0, 5).map((item, index) => (
                  <div key={index} className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                    <div className="text-sm text-starlight">{item.title}</div>
                    <div className="mt-1 text-xs text-dust">{item.correction}</div>
                    <div className="mt-2 flex items-center gap-1 text-xs text-azure">
                      <ArrowRight className="h-3 w-3" strokeWidth={1.5} />
                      {item.next_action}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <SectionTitle icon={<ArrowRight className="h-4 w-4 text-starlight" strokeWidth={1.5} />} title="调整方案" />
              {(review.content.adjustments || []).map((item, index) => (
                <div key={index} className="rounded-lg border border-white/5 bg-white/[0.02] p-3 text-sm text-starlight">{item}</div>
              ))}
            </div>
          </section>
        ) : (
          <section className="text-sm text-dust">还没有成长审核。</section>
        )}
      </div>
    </div>
  )
}
