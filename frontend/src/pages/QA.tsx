import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Send, ThumbsUp, ThumbsDown, Loader2, Sparkles, FileText, Check, X, Brain, Plus, Trash2, ChevronRight, MessageSquare, Pencil, Wrench, Layers, Save, ShieldCheck, Scale } from 'lucide-react'
import { api, type QaAskResponse, type Citation, type UserMemory, type QaSession, type ToolCall, type CardDraft, type FinalizeCardResponse, type KnowledgeCard, type QaResearchResponse } from '@/api/client'
import { useAppStore } from '@/store'
import { cn } from '@/lib/utils'
import { MarkdownView } from '@/components/MarkdownView'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  qa_id?: number
  feedback?: 'up' | 'down'
  memories_used?: UserMemory[]
  tools_used?: ToolCall[]
  cards_used?: KnowledgeCard[]
  card_draft?: CardDraft | null
  card_saved?: boolean
  research?: QaResearchResponse | null
}

// 生成会话 ID
function genSessionId() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

const MEMORY_TYPE_LABEL: Record<UserMemory['type'], string> = {
  preference: '偏好',
  fact: '事实',
  correction: '修正',
  term: '术语',
  ocr_correction: 'OCR 修正',
  ocr_addition: 'OCR 补充',
}

const TOOL_LABEL: Record<string, string> = {
  search_notes: '检索笔记',
  search_memory: '检索记忆',
  add_memory: '学习记忆',
}

export default function QA() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [asking, setAsking] = useState(false)
  const [correctingId, setCorrectingId] = useState<number | null>(null)
  const [correction, setCorrection] = useState('')
  const [sessionId, setSessionId] = useState<string>(genSessionId)
  const [memories, setMemories] = useState<UserMemory[]>([])
  const [sessions, setSessions] = useState<QaSession[]>([])
  const [showMemoryPanel, setShowMemoryPanel] = useState(false)
  const [showSessionsPanel, setShowSessionsPanel] = useState(true)
  const [newMemType, setNewMemType] = useState<UserMemory['type']>('preference')
  const [newMemContent, setNewMemContent] = useState('')
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  // 卡片弹窗 state
  const [cardModalDraft, setCardModalDraft] = useState<CardDraft | null>(null)
  const [cardModalQaId, setCardModalQaId] = useState<number | null>(null)
  const [cardUserAnswer, setCardUserAnswer] = useState('')
  const [cardSubmitting, setCardSubmitting] = useState(false)
  const [cardResult, setCardResult] = useState<FinalizeCardResponse | null>(null)
  const [cardGeneratingId, setCardGeneratingId] = useState<number | null>(null)
  const [savedCards, setSavedCards] = useState<Record<number, number>>({})
  const [researchLoadingId, setResearchLoadingId] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { refresh } = useAppStore()

  // 初始加载：会话列表 + 记忆列表
  useEffect(() => {
    loadSessions()
    loadMemories()
  }, [])

  const loadSavedCards = useCallback(() => {
    api.listCards(500)
      .then((res) => {
        const next: Record<number, number> = {}
        res.items.forEach((card) => {
          if (card.qa_id) next[card.qa_id] = card.id
        })
        setSavedCards(next)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadSavedCards()
  }, [loadSavedCards])

  // 加载某个会话的历史消息
  const loadSessionHistory = useCallback(async (sid: string) => {
    try {
      const res = await api.getQaHistory(100, 0, sid)
      const paired: ChatMessage[] = []
      // 按 created_at 升序返回（后端已按 ASC 排序）
      res.items.forEach((h) => {
        paired.push({ role: 'user', content: h.question })
        paired.push({
          role: 'assistant',
          content: h.answer,
          citations: h.citations ?? [],
          qa_id: h.id,
          card_draft: h.card_draft ?? null,
        })
      })
      setMessages(paired)
    } catch {
      setMessages([])
    }
  }, [])

  // 选中会话
  const selectSession = useCallback((sid: string) => {
    setSessionId(sid)
    loadSessionHistory(sid)
  }, [loadSessionHistory])

  const loadSessions = () => {
    api.listSessions(50).then((res) => setSessions(res.items)).catch(() => {})
  }

  const loadMemories = () => {
    api.listMemories().then((res) => setMemories(res.items)).catch(() => {})
  }

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
      const res: QaAskResponse = await api.ask(q, sessionId)
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: res.answer,
          citations: res.citations,
          qa_id: res.qa_id,
          memories_used: res.memories_used?.map((mu) => mu.memory),
          tools_used: res.tools_used,
          cards_used: res.cards_used,
          card_draft: res.card_draft ?? null,
        },
      ])
      refresh()
      // 问答后刷新会话列表（新会话会写入 qa_sessions 表）
      loadSessions()
      // 如果 Agent 调用了 add_memory，刷新记忆列表
      if (res.tools_used?.some((t) => t.name === 'add_memory')) {
        loadMemories()
      }
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `问答失败：${e instanceof Error ? e.message : '未知错误'}` },
      ])
    } finally {
      setAsking(false)
    }
  }, [input, asking, refresh, sessionId])

  const sendFeedback = async (qa_id: number, rating: 'up' | 'down') => {
    setMessages((m) => m.map((msg) => (msg.qa_id === qa_id ? { ...msg, feedback: rating } : msg)))
    try {
      await api.submitFeedback(qa_id, rating)
      refresh()
      loadMemories()
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
      loadMemories()
    } catch {
      /* 忽略 */
    }
  }

  // 新建会话
  const newSession = () => {
    setMessages([])
    setSessionId(genSessionId())
    setEditingSessionId(null)
  }

  // 重命名会话
  const startRenameSession = (s: QaSession) => {
    setEditingSessionId(s.session_id)
    setEditingTitle(s.title || '')
  }

  const submitRenameSession = async () => {
    if (!editingSessionId || !editingTitle.trim()) {
      setEditingSessionId(null)
      return
    }
    try {
      await api.renameSession(editingSessionId, editingTitle.trim())
      loadSessions()
    } catch {
      /* 忽略 */
    }
    setEditingSessionId(null)
  }

  // 删除会话
  const deleteSession = async (sid: string) => {
    if (!confirm('删除该会话？该会话的所有问答记录将永久删除。')) return
    try {
      await api.deleteSession(sid)
      // 如果删的是当前会话，开新会话
      if (sid === sessionId) {
        newSession()
      }
      loadSessions()
    } catch {
      /* 忽略 */
    }
  }

  // 添加记忆
  const addMemory = async () => {
    if (!newMemContent.trim()) return
    try {
      await api.addMemory({ type: newMemType, content: newMemContent.trim(), weight: 0.6 })
      setNewMemContent('')
      loadMemories()
    } catch (e) {
      alert(`添加失败：${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  // 删除记忆
  const deleteMemory = async (id: number) => {
    if (!confirm('删除这条记忆？')) return
    try {
      await api.deleteMemory(id)
      loadMemories()
    } catch {
      /* 忽略 */
    }
  }

  // —— 知识卡片 ——
  // 打开卡片弹窗（接收 assistant 消息里的 card_draft）
  const openCardModal = (draft: CardDraft, qaId: number | undefined) => {
    setCardModalDraft(draft)
    setCardModalQaId(qaId ?? null)
    setCardUserAnswer('')
    setCardResult(null)
  }

  const updateCardDraft = (field: 'title' | 'core_summary' | 'key_conclusion' | 'application_scenario', value: string) => {
    setCardModalDraft((draft) => (draft ? { ...draft, [field]: value } : draft))
  }

  const makeCardDraft = async (qaId: number) => {
    if (cardGeneratingId) return
    setCardGeneratingId(qaId)
    try {
      const res = await api.createCardDraft(qaId)
      setMessages((m) => m.map((msg) => (
        msg.qa_id === qaId ? { ...msg, card_draft: res.card_draft } : msg
      )))
      openCardModal(res.card_draft, qaId)
    } catch (e) {
      alert(`知识卡片生成失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setCardGeneratingId(null)
    }
  }

  const closeCardModal = () => {
    setCardModalDraft(null)
    setCardModalQaId(null)
    setCardUserAnswer('')
    setCardResult(null)
    setCardSubmitting(false)
  }

  const runResearch = async (qaId: number, mode: 'verify' | 'debate') => {
    if (researchLoadingId) return
    setResearchLoadingId(qaId)
    try {
      const res = await api.research(qaId, mode, sessionId)
      setMessages((m) => m.map((msg) => (
        msg.qa_id === qaId ? { ...msg, research: res, card_draft: res.card_draft ?? msg.card_draft } : msg
      )))
      if (mode === 'debate' && res.card_draft) {
        loadSavedCards()
      }
    } catch (e) {
      alert(`${mode === 'verify' ? '验证' : '辩论'}报告生成失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setResearchLoadingId(null)
    }
  }

  // 提交卡片（带用户答案或跳过）
  const submitCard = async (skip: boolean = false) => {
    if (!cardModalDraft) return
    setCardSubmitting(true)
    try {
      const res = await api.finalizeCard({
        ...cardModalDraft,
        qa_id: cardModalQaId,
        user_answer: skip ? '' : cardUserAnswer,
      })
      setCardResult(res)
      // 标记该消息的卡片已存档
      if (cardModalQaId) {
        setSavedCards((prev) => ({ ...prev, [cardModalQaId]: res.card_id }))
        setMessages((m) => m.map((msg) =>
          msg.qa_id === cardModalQaId ? { ...msg, card_saved: true } : msg
        ))
      }
    } catch (e) {
      alert(`卡片存档失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setCardSubmitting(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部标题 */}
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-3 md:px-8 md:py-4">
        <div className="flex items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-base text-starlight md:text-xl">智能问答</h1>
          <span className="hidden font-mono text-[10px] text-dust/60 md:inline">
            Agent · 长期记忆
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={newSession}
            className="btn-ghost px-2 py-1.5 text-xs"
            title="开始新会话"
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden md:inline">新会话</span>
          </button>
          <button
            onClick={() => setShowSessionsPanel(!showSessionsPanel)}
            className={cn(
              'btn-ghost flex items-center gap-1.5 px-2 py-1.5 text-xs',
              showSessionsPanel && 'text-flux',
            )}
            title="会话列表"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span className="hidden md:inline">会话</span>
            {sessions.length > 0 && (
              <span className="rounded bg-flux/20 px-1 text-[10px] text-flux">{sessions.length}</span>
            )}
          </button>
          <button
            onClick={() => setShowMemoryPanel(!showMemoryPanel)}
            className={cn(
              'btn-ghost flex items-center gap-1.5 px-2 py-1.5 text-xs',
              showMemoryPanel && 'text-flux',
            )}
            title="长期记忆管理"
          >
            <Brain className="h-3.5 w-3.5" />
            <span className="hidden md:inline">记忆</span>
            {memories.length > 0 && (
              <span className="rounded bg-flux/20 px-1 text-[10px] text-flux">{memories.length}</span>
            )}
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* 左侧：会话列表 */}
        {showSessionsPanel && (
          <aside className="flex w-60 flex-col border-r border-white/5 bg-void-300/30 backdrop-blur-xl md:w-72">
            <div className="border-b border-white/5 px-4 py-3">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-azure" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">会话</h2>
              </div>
              <p className="mt-1 text-[11px] text-dust/70">
                所有会话共用同一长期记忆库。点击切换历史会话。
              </p>
            </div>

            <div className="flex-1 overflow-y-auto p-2">
              {/* 当前会话（未发送任何消息的） */}
              {sessions.length === 0 && (
                <div
                  className={cn(
                    'mb-1.5 cursor-pointer rounded-md border px-2.5 py-2',
                    'border-flux/30 bg-flux/5'
                  )}
                >
                  <div className="truncate text-xs text-starlight/90">(新会话)</div>
                  <div className="mt-0.5 font-mono text-[9px] text-dust/50">未发送消息</div>
                </div>
              )}

              {sessions.map((s) => {
                const isCurrent = s.session_id === sessionId
                const isEditing = editingSessionId === s.session_id
                return (
                  <div
                    key={s.session_id}
                    className={cn(
                      'group mb-1.5 cursor-pointer rounded-md border px-2.5 py-2 transition-all',
                      isCurrent
                        ? 'border-flux/40 bg-flux/10'
                        : 'border-white/5 bg-white/[0.02] hover:border-azure/20 hover:bg-azure/5'
                    )}
                    onClick={() => !isEditing && selectSession(s.session_id)}
                  >
                    {isEditing ? (
                      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <input
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') submitRenameSession()
                            if (e.key === 'Escape') setEditingSessionId(null)
                          }}
                          className="flex-1 rounded border border-flux/30 bg-void-200/50 px-1.5 py-0.5 text-xs text-starlight focus:outline-none"
                          autoFocus
                        />
                        <button onClick={submitRenameSession} className="text-flux hover:opacity-80">
                          <Check className="h-3 w-3" />
                        </button>
                        <button onClick={() => setEditingSessionId(null)} className="text-dust hover:text-rose">
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-start gap-1.5">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-xs font-medium text-starlight/90">
                              {s.title || '(未命名会话)'}
                            </div>
                            {s.last_question && (
                              <div className="mt-0.5 truncate text-[10px] text-dust/60">
                                {s.last_question}
                              </div>
                            )}
                          </div>
                          <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                            <button
                              onClick={(e) => { e.stopPropagation(); startRenameSession(s) }}
                              className="text-dust hover:text-flux"
                              title="重命名"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteSession(s.session_id) }}
                              className="text-dust hover:text-rose"
                              title="删除"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                        <div className="mt-1 flex items-center gap-2 font-mono text-[9px] text-dust/50">
                          <span>{s.msg_count} 条</span>
                          <span>·</span>
                          <span>{new Date(s.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      </>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="border-t border-white/5 px-3 py-2 text-[10px] text-dust/50">
              <ChevronRight className="mr-1 inline h-3 w-3" />
              所有会话共用同一长期记忆库
            </div>
          </aside>
        )}

        {/* 主对话区 */}
        <div className="flex min-w-0 flex-1 flex-col">
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
                  <p className="mt-2 max-w-md text-xs text-dust/60">
                    Agent 可主动检索笔记、检索记忆、学习用户偏好。点赞/点踩+修正会让 Brain 越用越懂你。
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
                        <MarkdownView content={msg.content} />
                      </div>

                      {/* Agent 调用的工具 */}
                      {msg.tools_used && msg.tools_used.length > 0 && (
                        <div className="ml-1 flex flex-wrap items-center gap-1">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-amber/70">
                            <Wrench className="mr-1 inline h-3 w-3" />Agent 工具
                          </span>
                          {msg.tools_used.map((t, idx) => (
                            <span
                              key={idx}
                              className="rounded border border-amber/20 bg-amber/5 px-1.5 py-0.5 text-[10px] text-amber/80"
                              title={t.result_preview}
                            >
                              {TOOL_LABEL[t.name] || t.name}
                              {t.name === 'add_memory' && ' ✓'}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* 引用的长期记忆 */}
                      {msg.cards_used && msg.cards_used.length > 0 && (
                        <div className="ml-1 flex flex-wrap items-center gap-1">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-flux/70">
                            <Layers className="mr-1 inline h-3 w-3" />复用卡片
                          </span>
                          {msg.cards_used.map((card) => (
                            <Link
                              key={card.id}
                              to={`/cards/${card.id}`}
                              className="rounded border border-flux/20 bg-flux/5 px-1.5 py-0.5 text-[10px] text-flux/80 hover:bg-flux/10"
                            >
                              {card.title.slice(0, 24)}
                              {card.title.length > 24 ? '…' : ''}
                            </Link>
                          ))}
                        </div>
                      )}

                      {/* 引用的长期记忆 */}
                      {msg.memories_used && msg.memories_used.length > 0 && (
                        <div className="ml-1 flex flex-wrap items-center gap-1">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-azure/60">
                            <Brain className="mr-1 inline h-3 w-3" />已参考记忆
                          </span>
                          {msg.memories_used.map((m) => (
                            <span
                              key={m.id}
                              className="rounded border border-azure/20 bg-azure/5 px-1.5 py-0.5 text-[10px] text-azure/80"
                              title={m.content}
                            >
                              [{MEMORY_TYPE_LABEL[m.type]}] {m.content.slice(0, 30)}
                              {m.content.length > 30 ? '…' : ''}
                            </span>
                          ))}
                        </div>
                      )}

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

                      {/* 存为知识卡片按钮 */}
                      {msg.qa_id && (
                        <div className="ml-1 flex flex-wrap items-center gap-2">
                          <button
                            onClick={() => runResearch(msg.qa_id!, 'verify')}
                            disabled={researchLoadingId !== null}
                            className="inline-flex items-center gap-1 rounded-full border border-azure/30 bg-azure/10 px-2.5 py-1 font-mono text-[10px] text-azure transition-colors hover:bg-azure/20"
                          >
                            <ShieldCheck className="h-3 w-3" />
                            {researchLoadingId === msg.qa_id ? '联网验证中…' : '验证观点'}
                          </button>
                          <button
                            onClick={() => runResearch(msg.qa_id!, 'debate')}
                            disabled={researchLoadingId !== null}
                            className="inline-flex items-center gap-1 rounded-full border border-amber/30 bg-amber/10 px-2.5 py-1 font-mono text-[10px] text-amber transition-colors hover:bg-amber/20"
                          >
                            <Scale className="h-3 w-3" />
                            {researchLoadingId === msg.qa_id ? '联网辩论中…' : '辩论观点'}
                          </button>
                          {savedCards[msg.qa_id] ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-flux/30 bg-flux/10 px-2.5 py-1 font-mono text-[10px] text-flux">
                              <Layers className="h-3 w-3" />
                              已存为知识卡片
                              <Link to={`/cards/${savedCards[msg.qa_id]}`} className="ml-1 underline hover:no-underline">查看</Link>
                            </span>
                          ) : (
                            <button
                              onClick={() => (
                                msg.card_draft
                                  ? openCardModal(msg.card_draft, msg.qa_id)
                                  : makeCardDraft(msg.qa_id)
                              )}
                              disabled={cardGeneratingId === msg.qa_id}
                              className="inline-flex items-center gap-1 rounded-full border border-flux/30 bg-flux/10 px-2.5 py-1 font-mono text-[10px] text-flux transition-colors hover:bg-flux/20"
                            >
                              <Layers className="h-3 w-3" />
                              {msg.card_draft ? '存为知识卡片' : (cardGeneratingId === msg.qa_id ? '生成草稿中…' : '制作知识卡片')}
                            </button>
                          )}
                        </div>
                      )}

                      {/* 联网验证 / 辩论报告 */}
                      {msg.research && (
                        <div className="ml-1 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[10px] uppercase tracking-wider text-dust/60">
                              {msg.research.mode === 'verify' ? '联网验证' : '联网辩论'}
                            </span>
                            <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-dust">
                              {msg.research.web_evidence_count} 条网络证据
                            </span>
                            {typeof msg.research.history_used_count === 'number' && (
                              <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-dust">
                                参考 {msg.research.history_used_count} 轮历史
                              </span>
                            )}
                            {msg.research.keywords && msg.research.keywords.length > 0 && (
                              <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-dust/80">
                                {msg.research.keywords.slice(0, 3).join(' · ')}
                              </span>
                            )}
                            {msg.research.debate_recommended && (
                              <span className="rounded bg-amber/10 px-1.5 py-0.5 text-[10px] text-amber/90">
                                建议辩论
                              </span>
                            )}
                            {msg.research.mode === 'debate' && msg.card_draft && (
                              <span className="rounded bg-flux/10 px-1.5 py-0.5 text-[10px] text-flux">
                                卡片草稿已生成
                              </span>
                            )}
                            {msg.research.search_note && (
                              <span className="text-[10px] text-rose/80">搜索可能不完整</span>
                            )}
                          </div>
                          <MarkdownView content={msg.research.report} />
                          {msg.research.sources.length > 0 && (
                            <div className="mt-3 space-y-1.5 border-t border-white/5 pt-3">
                              {msg.research.sources.map((source) => (
                                <a
                                  key={source.url}
                                  href={source.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="block text-[11px] leading-relaxed text-dust hover:text-azure"
                                >
                                  {source.title}
                                </a>
                              ))}
                            </div>
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
                            placeholder="期望的正确答案或补充信息（会作为长期记忆保存）…"
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
                  <span className="font-mono text-xs text-dust">Agent 检索笔记与记忆中…</span>
                </div>
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div className="safe-bottom border-t border-white/5 px-3 py-3 md:px-8 md:py-4">
            <div className="flex items-end gap-2 rounded-xl border border-white/10 bg-void-200/50 px-3 py-2 backdrop-blur-md focus-within:border-flux/30 md:px-4 md:py-2.5">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  // Enter 发送，Shift+Enter 换行（标准聊天 UX）
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    ask()
                  }
                }}
                rows={1}
                placeholder="向你的笔记知识库提问…（Enter 发送，Shift+Enter 换行）"
                className="max-h-32 flex-1 resize-none bg-transparent text-base text-starlight placeholder:text-dust/50 focus:outline-none md:text-sm"
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

        {/* 右侧：记忆侧栏 */}
        {showMemoryPanel && (
          <aside className="flex w-72 flex-col border-l border-white/5 bg-void-300/30 backdrop-blur-xl md:w-80">
            <div className="border-b border-white/5 px-4 py-3">
              <div className="flex items-center gap-2">
                <Brain className="h-4 w-4 text-azure" strokeWidth={1.5} />
                <h2 className="font-display text-sm text-starlight">长期记忆</h2>
              </div>
              <p className="mt-1 text-[11px] text-dust/70">
                所有会话共用同一记忆库。Agent 会主动学习用户偏好。
              </p>
            </div>

            {/* 新增记忆 */}
            <div className="border-b border-white/5 p-3">
              <div className="mb-2 flex items-center gap-1.5">
                <select
                  value={newMemType}
                  onChange={(e) => setNewMemType(e.target.value as UserMemory['type'])}
                  className="rounded border border-white/10 bg-void-200/50 px-2 py-1 text-xs text-starlight focus:outline-none"
                >
                  <option value="preference">偏好</option>
                  <option value="fact">事实</option>
                  <option value="correction">修正</option>
                  <option value="term">术语</option>
                  <option value="ocr_correction">OCR 修正</option>
                  <option value="ocr_addition">OCR 补充</option>
                </select>
                <input
                  value={newMemContent}
                  onChange={(e) => setNewMemContent(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addMemory()}
                  placeholder="手动添加一条记忆…"
                  className="flex-1 rounded border border-white/10 bg-void-200/50 px-2 py-1 text-xs text-starlight placeholder:text-dust/40 focus:outline-none"
                />
                <button
                  onClick={addMemory}
                  disabled={!newMemContent.trim()}
                  className="flex h-7 w-7 items-center justify-center rounded bg-flux/15 text-flux disabled:opacity-30"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* 记忆列表 */}
            <div className="flex-1 overflow-y-auto p-2">
              {memories.length === 0 ? (
                <div className="px-3 py-6 text-center text-[11px] text-dust/50">
                  暂无记忆。在问答中点踩并填写修正，或手动添加，Brain 会越用越懂你。
                </div>
              ) : (
                memories.map((m) => (
                  <div
                    key={m.id}
                    className="group mb-1.5 rounded-md border border-white/5 bg-white/[0.02] px-2.5 py-2 hover:border-rose/20"
                  >
                    <div className="flex items-start gap-1.5">
                      <span className="mt-0.5 rounded bg-azure/10 px-1 py-0.5 text-[9px] text-azure/80">
                        {MEMORY_TYPE_LABEL[m.type]}
                      </span>
                      <span className="flex-1 text-[11px] leading-relaxed text-starlight/80">{m.content}</span>
                      <button
                        onClick={() => deleteMemory(m.id)}
                        className="opacity-0 transition-opacity group-hover:opacity-100"
                        title="删除"
                      >
                        <Trash2 className="h-3 w-3 text-dust hover:text-rose" />
                      </button>
                    </div>
                    <div className="mt-1 flex items-center gap-2 font-mono text-[9px] text-dust/50">
                      <span>权重 {m.weight.toFixed(2)}</span>
                      {m.use_count > 0 && <span>· 用过 {m.use_count} 次</span>}
                      <span className="ml-auto">
                        {m.source === 'feedback' ? '反馈学习' :
                         m.source === 'manual' ? '手动' :
                         m.source === 'auto_learn' ? 'Agent 学习' :
                         m.source === 'manual_edit' ? (m.type === 'ocr_addition' ? 'OCR 补充' : 'OCR 修正') : m.source}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="border-t border-white/5 px-3 py-2 text-[10px] text-dust/50">
              <ChevronRight className="mr-1 inline h-3 w-3" />
              问答时自动检索记忆注入上下文
            </div>
          </aside>
        )}
      </div>

      {/* 知识卡片弹窗 */}
      {cardModalDraft && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-void-500/80 p-4 backdrop-blur-sm"
          onClick={closeCardModal}
        >
          <div
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-flux/30 bg-void-200 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between border-b border-white/5 px-5 py-3">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-flux" strokeWidth={1.5} />
                <h3 className="font-display text-sm text-starlight">存为知识卡片</h3>
              </div>
              <button onClick={closeCardModal} className="text-dust hover:text-starlight">
                <X className="h-4 w-4" />
              </button>
            </div>

            {cardResult ? (
              /* 存档成功后的结果展示 */
              <div className="space-y-4 p-5">
                <div className="flex items-center gap-2 text-flux">
                  <Check className="h-5 w-5" />
                  <span className="text-sm font-medium">知识卡片已存档</span>
                  <span className="font-mono text-[10px] text-dust/60">
                    #{cardResult.card_id} · 链接 {cardResult.linked_notes} 篇笔记
                  </span>
                </div>
                {cardResult.ai_supplement && (
                  <div className="rounded-lg border border-amber/30 bg-amber/5 p-3">
                    <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-amber">
                      <Sparkles className="h-3 w-3" />
                      AI 补充
                      <span className="text-dust/60">
                        ({cardResult.verdict === 'correct' ? '回答正确' : cardResult.verdict === 'skipped' ? '跳过回答' : '需补充'})
                      </span>
                    </div>
                    <MarkdownView content={cardResult.ai_supplement} />
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Link
                    to={`/cards/${cardResult.card_id}`}
                    className="btn-ghost px-3 py-1.5 text-xs"
                  >
                    查看卡片详情
                  </Link>
                  <button onClick={closeCardModal} className="btn-primary px-3 py-1.5 text-xs">
                    完成
                  </button>
                </div>
              </div>
            ) : (
              /* 草稿编辑 + Agent 提问 */
              <div className="space-y-4 p-5">
                {/* 卡片预览 */}
                <div className="space-y-3">
                  <div>
                    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-dust/60">标题</div>
                    <input
                      value={cardModalDraft.title}
                      onChange={(e) => updateCardDraft('title', e.target.value)}
                      className="w-full rounded-md border border-white/10 bg-void-300/50 px-2.5 py-1.5 text-sm font-medium text-starlight focus:border-flux/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-flux/70">核心讲了什么</div>
                    <textarea
                      value={cardModalDraft.core_summary}
                      onChange={(e) => updateCardDraft('core_summary', e.target.value)}
                      rows={4}
                      className="w-full rounded-md border border-white/10 bg-void-300/50 px-2.5 py-1.5 text-sm leading-relaxed text-starlight/90 focus:border-flux/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-azure/70">关键结论</div>
                    <textarea
                      value={cardModalDraft.key_conclusion}
                      onChange={(e) => updateCardDraft('key_conclusion', e.target.value)}
                      rows={3}
                      className="w-full rounded-md border border-white/10 bg-void-300/50 px-2.5 py-1.5 text-sm leading-relaxed text-starlight/90 focus:border-azure/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-amber/70">落地场景</div>
                    <textarea
                      value={cardModalDraft.application_scenario}
                      onChange={(e) => updateCardDraft('application_scenario', e.target.value)}
                      rows={2}
                      placeholder="什么时候、怎么做可以使用这个知识？"
                      className="w-full rounded-md border border-white/10 bg-void-300/50 px-2.5 py-1.5 text-sm leading-relaxed text-starlight/90 placeholder:text-dust/40 focus:border-amber/30 focus:outline-none"
                    />
                  </div>
                  {cardModalDraft.source_note_ids.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="font-mono text-[10px] text-dust/60">关联笔记：</span>
                      {cardModalDraft.source_note_ids.map((nid) => (
                        <Link
                          key={nid}
                          to={`/notes/${nid}`}
                          className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-dust hover:border-azure/30 hover:text-azure"
                        >
                          #{nid}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>

                {/* Agent 提问 */}
                {cardModalDraft.agent_question && (
                  <div className="rounded-lg border border-flux/30 bg-flux/5 p-3">
                    <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-flux">
                      <Sparkles className="h-3 w-3" />
                      Agent 提问（检验你的理解）
                    </div>
                    <p className="text-sm text-starlight">{cardModalDraft.agent_question}</p>
                    <textarea
                      value={cardUserAnswer}
                      onChange={(e) => setCardUserAnswer(e.target.value)}
                      placeholder="在这里回答（按 Ctrl+Enter 提交，留空跳过由 AI 补充）…"
                      className="mt-2 w-full rounded-md border border-white/10 bg-void-300/50 px-2.5 py-1.5 text-sm text-starlight placeholder:text-dust/40 focus:border-flux/30 focus:outline-none"
                      rows={3}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitCard(false)
                      }}
                    />
                  </div>
                )}

                {/* 操作按钮 */}
                <div className="flex items-center justify-between border-t border-white/5 pt-3">
                  <button
                    onClick={() => submitCard(true)}
                    disabled={cardSubmitting}
                    className="btn-ghost px-3 py-1.5 text-xs"
                  >
                    跳过回答（AI 补充）
                  </button>
                  <div className="flex items-center gap-2">
                    <button onClick={closeCardModal} className="btn-ghost px-3 py-1.5 text-xs">
                      不存档
                    </button>
                    <button
                      onClick={() => submitCard(false)}
                      disabled={cardSubmitting || !cardModalDraft.title.trim() || !cardModalDraft.core_summary.trim() || !cardModalDraft.key_conclusion.trim()}
                      className="btn-primary flex items-center gap-1.5 px-3 py-1.5 text-xs"
                    >
                      {cardSubmitting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      存档卡片
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
