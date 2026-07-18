import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Send, ThumbsUp, ThumbsDown, Loader2, Sparkles, FileText, Check, X } from 'lucide-react'
import { api, type QaAskResponse, type Citation } from '@/api/client'
import { useAppStore } from '@/store'
import { cn } from '@/lib/utils'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  qa_id?: number
  feedback?: 'up' | 'down'
}

export default function QA() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [asking, setAsking] = useState(false)
  const [correctingId, setCorrectingId] = useState<number | null>(null)
  const [correction, setCorrection] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const { refresh } = useAppStore()

  // 加载历史（按时间正序，user/assistant 成对插入）
  useEffect(() => {
    api.getQaHistory(20, 0).then((res) => {
      const paired: ChatMessage[] = []
      res.items
        .slice()
        .reverse()
        .forEach((h) => {
          paired.push({ role: 'user', content: h.question })
          paired.push({ role: 'assistant', content: h.answer, citations: h.citations ?? [], qa_id: h.id })
        })
      setMessages(paired)
    })
  }, [])

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, asking])

  const ask = useCallback(async () => {
    const q = input.trim()
    if (!q || asking) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: q }])
    setAsking(true)
    try {
      const res: QaAskResponse = await api.ask(q)
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: res.answer, citations: res.citations, qa_id: res.qa_id },
      ])
      refresh()
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `问答失败：${e instanceof Error ? e.message : '未知错误'}` },
      ])
    } finally {
      setAsking(false)
    }
  }, [input, asking, refresh])

  const sendFeedback = async (qa_id: number, rating: 'up' | 'down') => {
    setMessages((m) => m.map((msg) => (msg.qa_id === qa_id ? { ...msg, feedback: rating } : msg)))
    try {
      await api.submitFeedback(qa_id, rating)
      refresh()
    } catch {
      /* 忽略反馈失败 */
    }
  }

  const submitCorrection = async (qa_id: number) => {
    if (!correction.trim()) return
    try {
      await api.submitFeedback(qa_id, 'down', correction.trim())
      setCorrectingId(null)
      setCorrection('')
      refresh()
    } catch {
      /* 忽略 */
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部标题 */}
      <div className="border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="flex items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-lg text-starlight md:text-xl">智能问答</h1>
        </div>
        <p className="mt-1 text-xs text-dust md:text-sm">基于知识库的 RAG 问答 · 回答仅引用已入库笔记</p>
      </div>

      {/* 对话区 */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-3 py-4 md:space-y-6 md:px-8 md:py-6">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="relative">
              <div className="absolute inset-0 rounded-full bg-flux/20 blur-2xl" />
              <Sparkles className="relative h-10 w-10 text-flux" strokeWidth={1} />
            </div>
            <div>
              <div className="font-display text-lg text-starlight/80">向你的笔记提问</div>
              <p className="mt-1 max-w-sm text-sm text-dust">
                例如：「我最近关于需求分析的笔记有哪些？」「甲方需求图里提到哪些关键点？」
              </p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={cn('flex animate-fade-up', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div className={cn('max-w-[88%] md:max-w-[78%]', msg.role === 'user' ? '' : 'w-full md:max-w-3xl')}>
              {msg.role === 'user' ? (
                <div className="rounded-2xl rounded-br-sm border border-flux/20 bg-flux/10 px-4 py-2.5 text-sm text-starlight">
                  {msg.content}
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="glass-panel rounded-2xl rounded-bl-sm px-4 py-3">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className="font-mono text-[10px] uppercase tracking-wider text-flux/70">Brain</span>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-starlight/90">{msg.content}</p>
                  </div>

                  {/* 引用笔记 */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="ml-1 space-y-2">
                      <div className="font-mono text-[10px] uppercase tracking-wider text-dust/60">引用笔记</div>
                      <div className="grid gap-2 sm:grid-cols-1 md:grid-cols-2">
                        {msg.citations.map((c) => (
                          <Link
                            key={c.note_id}
                            to={`/notes/${c.note_id}`}
                            className="group flex items-start gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 transition-all hover:border-azure/30 hover:bg-azure/5"
                          >
                            <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-dust group-hover:text-azure" strokeWidth={1.5} />
                            <div className="min-w-0">
                              <div className="truncate text-xs font-medium text-starlight">{c.title}</div>
                              <div className="mt-0.5 line-clamp-2 text-[11px] text-dust">{c.snippet}</div>
                              <div className="mt-1 font-mono text-[10px] text-dust/50">
                                #{c.note_id} · 相关度 {c.score}
                              </div>
                            </div>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 反馈按钮 */}
                  {msg.qa_id && (
                    <div className="ml-1 flex items-center gap-2">
                      <button
                        onClick={() => sendFeedback(msg.qa_id!, 'up')}
                        disabled={msg.feedback !== undefined}
                        className={cn(
                          'flex h-7 w-7 items-center justify-center rounded-full border transition-all',
                          msg.feedback === 'up'
                            ? 'border-flux/50 bg-flux/15 text-flux'
                            : 'border-white/10 text-dust hover:border-flux/30 hover:text-flux',
                          msg.feedback !== undefined && msg.feedback !== 'up' && 'opacity-40',
                        )}
                      >
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => {
                          setCorrectingId(correctingId === msg.qa_id ? null : msg.qa_id ?? null)
                          setCorrection('')
                        }}
                        disabled={msg.feedback !== undefined}
                        className={cn(
                          'flex h-7 w-7 items-center justify-center rounded-full border transition-all',
                          msg.feedback === 'down'
                            ? 'border-rose/50 bg-rose/15 text-rose'
                            : 'border-white/10 text-dust hover:border-rose/30 hover:text-rose',
                          msg.feedback !== undefined && msg.feedback !== 'down' && 'opacity-40',
                        )}
                      >
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </button>
                      {msg.feedback && (
                        <span className="font-mono text-[10px] text-dust/60">
                          <Check className="mr-1 inline h-3 w-3" />
                          已反馈
                        </span>
                      )}
                    </div>
                  )}

                  {/* 修正输入框 */}
                  {correctingId === msg.qa_id && (
                    <div className="ml-1 flex items-center gap-2 rounded-lg border border-rose/20 bg-rose/5 p-2">
                      <input
                        value={correction}
                        onChange={(e) => setCorrection(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submitCorrection(msg.qa_id!)}
                        placeholder="期望的正确答案或补充信息…"
                        className="flex-1 bg-transparent text-sm text-starlight placeholder:text-dust/50 focus:outline-none"
                        autoFocus
                      />
                      <button onClick={() => submitCorrection(msg.qa_id!)} className="btn-ghost px-2 py-1 text-xs">
                        <Check className="h-3 w-3" />
                      </button>
                      <button onClick={() => { setCorrectingId(null); setCorrection('') }} className="btn-ghost px-2 py-1 text-xs">
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {asking && (
          <div className="flex justify-start">
            <div className="glass-panel flex items-center gap-2 rounded-2xl rounded-bl-sm px-4 py-3">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-flux" />
              <span className="font-mono text-xs text-dust">检索知识库中…</span>
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="safe-bottom border-t border-white/5 px-3 py-3 md:px-8 md:py-4">
        <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-void-200/50 px-3 py-2 backdrop-blur-md focus-within:border-flux/30 md:px-4 md:py-2.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && ask()}
            placeholder="向你的笔记知识库提问…"
            className="flex-1 bg-transparent text-base text-starlight placeholder:text-dust/50 focus:outline-none md:text-sm"
          />
          <button
            onClick={ask}
            disabled={!input.trim() || asking}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-flux/15 text-flux transition-all hover:bg-flux/25 active:scale-95 disabled:opacity-30 md:h-8 md:w-8"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
