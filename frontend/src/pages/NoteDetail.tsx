import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Copy, Check, RefreshCw, Smartphone, AppWindow, Calendar } from 'lucide-react'
import { api, type Note } from '@/api/client'
import { StatusBadge, formatDate } from '@/components/StatusBadge'
import { cn } from '@/lib/utils'

export default function NoteDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [note, setNote] = useState<Note | null>(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  // 移动端 Tab：原图 / OCR
  const [mobileTab, setMobileTab] = useState<'file' | 'ocr'>('file')

  useEffect(() => {
    if (!id) return
    setLoading(true)
    api.getNote(Number(id)).then(setNote).finally(() => setLoading(false))
  }, [id])

  const copyOcr = async () => {
    if (!note?.ocr_text) return
    await navigator.clipboard.writeText(note.ocr_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  const reprocess = async () => {
    if (!note) return
    setReprocessing(true)
    try {
      await api.reprocessNote(note.id)
      // 轮询等待完成
      const poll = async () => {
        const updated = await api.getNote(note.id)
        setNote(updated)
        if (updated.status === 'processing' || updated.status === 'pending') {
          setTimeout(poll, 1500)
        } else {
          setReprocessing(false)
        }
      }
      setTimeout(poll, 1500)
    } catch {
      setReprocessing(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-flux/30 border-t-flux" />
      </div>
    )
  }

  if (!note) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-dust">
        <p>笔记不存在</p>
        <button onClick={() => navigate('/notes')} className="btn-ghost">返回列表</button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部栏 */}
      <div className="safe-top flex items-center justify-between gap-2 border-b border-white/5 px-3 py-3 md:px-6 md:py-4">
        <div className="flex min-w-0 items-center gap-2 md:gap-3">
          <button onClick={() => navigate('/notes')} className="btn-ghost shrink-0 px-2 py-1.5">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0">
            <h1 className="truncate font-display text-base text-starlight md:text-lg">{note.title ?? '(未命名)'}</h1>
            <div className="mt-0.5 flex items-center gap-2 md:gap-3">
              <StatusBadge status={note.status} />
              <span className="font-mono text-[10px] text-dust md:text-[11px]">#{note.id}</span>
            </div>
          </div>
        </div>
        <button onClick={reprocess} disabled={reprocessing} className="btn-ghost shrink-0 px-2 py-1.5 text-xs md:px-3 md:py-2">
          <RefreshCw className={`h-3.5 w-3.5 ${reprocessing ? 'animate-spin' : ''}`} />
          <span className="hidden md:inline">{reprocessing ? '重新处理中…' : '重新 OCR'}</span>
        </button>
      </div>

      {/* 元信息条 */}
      <div className="flex flex-wrap items-center gap-3 border-b border-white/5 px-3 py-2.5 font-mono text-[11px] text-dust md:gap-4 md:px-6 md:py-3 md:text-xs">
        <span className="flex items-center gap-1.5">
          <Smartphone className="h-3.5 w-3.5" strokeWidth={1.5} />
          {note.source_device ?? '未知设备'}
        </span>
        <span className="flex items-center gap-1.5">
          <AppWindow className="h-3.5 w-3.5" strokeWidth={1.5} />
          {note.source_app ?? '未知应用'}
        </span>
        <span className="flex items-center gap-1.5">
          <Calendar className="h-3.5 w-3.5" strokeWidth={1.5} />
          {formatDate(note.created_at)}
        </span>
      </div>

      {/* 关键词 */}
      {note.keywords && note.keywords.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-white/5 px-3 py-2.5 md:px-6 md:py-3">
          <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-dust/60">关键词</span>
          {note.keywords.map((kw) => (
            <span key={kw} className="chip">{kw}</span>
          ))}
        </div>
      )}

      {/* 移动端 Tab 切换 */}
      <div className="flex border-b border-white/5 md:hidden">
        <button
          onClick={() => setMobileTab('file')}
          className={cn(
            'flex-1 py-2.5 text-xs font-medium transition-colors',
            mobileTab === 'file' ? 'border-b-2 border-flux text-flux' : 'text-dust',
          )}
        >
          原始文件
        </button>
        <button
          onClick={() => setMobileTab('ocr')}
          className={cn(
            'flex-1 py-2.5 text-xs font-medium transition-colors',
            mobileTab === 'ocr' ? 'border-b-2 border-flux text-flux' : 'text-dust',
          )}
        >
          OCR 文本
        </button>
      </div>

      {/* 双栏对照（桌面）/ 单栏切换（移动端） */}
      <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-2">
        {/* 原图 */}
        <div className={cn('flex flex-col overflow-hidden border-r border-white/5', mobileTab !== 'file' && 'hidden lg:flex')}>
          <div className="flex items-center justify-between border-b border-white/5 px-3 py-2 md:px-6 md:py-2.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust/70">原始文件</span>
            <a href={api.noteFileUrl(note.id)} target="_blank" rel="noreferrer" className="font-mono text-[10px] text-flux/70 hover:text-flux">
              新窗口 ↗
            </a>
          </div>
          <div className="flex-1 overflow-auto bg-void-500/30 p-3 md:p-6">
            <div className="mx-auto overflow-hidden rounded-lg border border-white/10 bg-void-300 shadow-panel">
              {note.file_path?.toLowerCase().endsWith('.pdf') ? (
                <iframe src={api.noteFileUrl(note.id)} title="原始文件" className="h-[70vh] w-full bg-white md:h-[80vh]" />
              ) : (
                <img src={api.noteFileUrl(note.id)} alt={note.title ?? ''} className="block w-full" />
              )}
            </div>
          </div>
        </div>

        {/* OCR 文本 */}
        <div className={cn('flex flex-col overflow-hidden', mobileTab !== 'ocr' && 'hidden lg:flex')}>
          <div className="flex items-center justify-between border-b border-white/5 px-3 py-2 md:px-6 md:py-2.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust/70">OCR 文本</span>
            <button
              onClick={copyOcr}
              disabled={!note.ocr_text}
              className="flex items-center gap-1.5 rounded-md border border-white/10 px-2 py-1 font-mono text-[10px] text-dust transition-colors hover:border-flux/30 hover:text-flux disabled:opacity-30"
            >
              {copied ? <Check className="h-3 w-3 text-flux" /> : <Copy className="h-3 w-3" />}
              {copied ? '已复制' : '复制'}
            </button>
          </div>
          <div className="flex-1 overflow-auto p-3 md:p-6">
            {note.summary && (
              <div className="mb-4 rounded-lg border border-flux/10 bg-flux/[0.03] p-3 md:mb-5 md:p-4">
                <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-flux/70">摘要</div>
                <p className="text-sm leading-relaxed text-starlight/85">{note.summary}</p>
              </div>
            )}
            {note.ocr_text ? (
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-starlight/80 md:text-sm">
                {note.ocr_text}
              </pre>
            ) : (
              <div className="rounded-lg border border-dashed border-white/10 px-4 py-8 text-center font-mono text-xs text-dust/50">
                {note.status === 'done' ? '该笔记未提取到 OCR 文本' : '笔记尚未完成 OCR 处理'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
