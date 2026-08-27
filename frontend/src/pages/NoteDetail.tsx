import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Copy, Check, RefreshCw, Smartphone, AppWindow, Calendar, Pencil, Save, X, BadgeCheck, RotateCcw, Trash2, FileText, Download } from 'lucide-react'
import { api, type Note } from '@/api/client'
import { StatusBadge, formatDate } from '@/components/StatusBadge'
import { MarkdownView } from '@/components/MarkdownView'
import { cn } from '@/lib/utils'

/**
 * 根据文件扩展名渲染原始文件预览。
 * - PDF：iframe 内嵌
 * - 图片（png/jpg/jpeg）：img 标签
 * - 文本型（txt/md/markdown）：iframe 以 text/plain 展示，浏览器原生支持
 * - Word（docx）：浏览器无法内嵌，显示下载按钮 + 提示
 */
function _renderOriginalFile(note: Note) {
  const fp = (note.file_path || '').toLowerCase()
  const url = api.noteFileUrl(note.id)
  if (fp.endsWith('.pdf')) {
    return <iframe src={url} title="原始文件" className="h-[70vh] w-full bg-white md:h-[80vh]" />
  }
  if (fp.endsWith('.png') || fp.endsWith('.jpg') || fp.endsWith('.jpeg')) {
    return <img src={url} alt={note.title ?? ''} className="block w-full" />
  }
  if (fp.endsWith('.txt') || fp.endsWith('.md') || fp.endsWith('.markdown')) {
    // iframe 直接加载文本文件，浏览器以 text/plain 渲染
    return (
      <iframe
        src={url}
        title="原始文件"
        className="h-[70vh] w-full bg-[#1a1a1a] text-sm md:h-[80vh]"
      />
    )
  }
  if (fp.endsWith('.docx')) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center md:h-[70vh]">
        <FileText className="h-12 w-12 text-amber" strokeWidth={1.2} />
        <div>
          <div className="font-display text-base text-starlight">Word 文档</div>
          <div className="mt-1 font-mono text-[11px] text-dust">
            浏览器无法内嵌预览 .docx，请下载查看
          </div>
        </div>
        <a
          href={url}
          download
          className="flex items-center gap-1.5 rounded-lg border border-flux/30 bg-flux/10 px-4 py-2 text-xs text-flux transition-colors hover:bg-flux/20"
        >
          <Download className="h-3.5 w-3.5" />
          下载 .docx
        </a>
        <div className="mt-2 max-w-xs font-mono text-[10px] text-dust/60">
          文本内容已自动抽取并展示在右侧「OCR 文本」面板
        </div>
      </div>
    )
  }
  // 兜底：未知类型，提供下载链接
  return (
    <div className="flex h-[40vh] items-center justify-center p-8 text-center">
      <a
        href={url}
        download
        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs text-starlight hover:bg-white/10"
      >
        <Download className="h-3.5 w-3.5" />
        下载原始文件
      </a>
    </div>
  )
}

export default function NoteDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [note, setNote] = useState<Note | null>(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  // 移动端 Tab：原图 / OCR
  const [mobileTab, setMobileTab] = useState<'file' | 'ocr'>('file')

  // 编辑模式
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editOcrText, setEditOcrText] = useState('')
  const [editMermaid, setEditMermaid] = useState('')
  const [editSummary, setEditSummary] = useState('')
  const [editKeywords, setEditKeywords] = useState('') // 逗号分隔
  const [editPreview, setEditPreview] = useState(false)
  const [saving, setSaving] = useState(false)

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
      // 轮询等待完成，最多 5 分钟（200 次 × 1.5s），超时提示用户手动重试
      let polls = 0
      const MAX_POLLS = 200
      const poll = async () => {
        polls += 1
        const updated = await api.getNote(note.id)
        setNote(updated)
        if (updated.status === 'processing' || updated.status === 'pending') {
          if (polls >= MAX_POLLS) {
            setReprocessing(false)
            // 超时：交由用户决定是否再次点击重试
            alert('OCR 处理超时（>5 分钟），可能 LLM 无响应。可稍后刷新查看，或再次点击重试。')
          } else {
            setTimeout(poll, 1500)
          }
        } else {
          setReprocessing(false)
        }
      }
      setTimeout(poll, 1500)
    } catch {
      setReprocessing(false)
    }
  }

  // 进入编辑模式
  const startEdit = () => {
    if (!note) return
    setEditTitle(note.title ?? '')
    setEditOcrText(note.ocr_text ?? '')
    setEditMermaid(note.mermaid ?? '')
    setEditSummary(note.summary ?? '')
    setEditKeywords((note.keywords ?? []).join(', '))
    setEditPreview(false)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
  }

  // 保存编辑
  const saveEdit = async () => {
    if (!note) return
    setSaving(true)
    try {
      const keywords = editKeywords
        .split(/[,，]/)
        .map((k) => k.trim())
        .filter(Boolean)
      const res = await api.editNote(note.id, {
        title: editTitle,
        ocr_text: editOcrText,
        summary: editSummary,
        keywords,
        mermaid: editMermaid,
        recompute_embedding: true,
      })
      setNote(res.note)
      setEditing(false)
    } catch (e) {
      alert(`保存失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setSaving(false)
    }
  }

  // 清除人工编辑标记
  const clearManualEdit = async () => {
    if (!note) return
    if (!confirm('清除人工编辑标记后，下次重新 OCR 将覆盖当前内容。是否继续？')) return
    try {
      await api.clearManualEdit(note.id)
      const updated = await api.getNote(note.id)
      setNote(updated)
    } catch (e) {
      alert(`清除失败：${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  // 删除笔记
  const [deleting, setDeleting] = useState(false)
  const deleteNote = async (hard: boolean) => {
    if (!note) return
    const tip = hard
      ? `永久删除笔记 #${note.id}？\n\n将同时删除：\n· 数据库记录（笔记 / links / 缩略图）\n· 物理文件：${note.file_path}\n\n此操作不可撤销。`
      : `删除笔记 #${note.id}？\n\n将删除数据库记录、links、缩略图，但保留物理文件（由 Syncthing 管理同步）。\n\n此操作不可撤销。`
    if (!confirm(tip)) return
    setDeleting(true)
    try {
      await api.deleteNote(note.id, hard)
      navigate('/notes')
    } catch (e) {
      alert(`删除失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setDeleting(false)
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
            <h1 className="truncate font-display text-base text-starlight md:text-lg">
              {note.title ?? '(未命名)'}
              {note.manually_edited && (
                <span className="ml-2 inline-flex items-center gap-1 rounded bg-flux/10 px-1.5 py-0.5 align-middle text-[10px] text-flux">
                  <BadgeCheck className="h-3 w-3" />已人工修正
                </span>
              )}
            </h1>
            <div className="mt-0.5 flex items-center gap-2 md:gap-3">
              <StatusBadge status={note.status} />
              <span className="font-mono text-[10px] text-dust md:text-[11px]">#{note.id}</span>
              {note.ocr_model && (
                <span className="font-mono text-[10px] text-dust/70 md:text-[11px]">
                  model: {note.ocr_model}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {editing ? (
            <>
              <button onClick={cancelEdit} disabled={saving} className="btn-ghost px-2 py-1.5 text-xs md:px-3 md:py-2">
                <X className="h-3.5 w-3.5" />
                <span className="hidden md:inline">取消</span>
              </button>
              <button onClick={saveEdit} disabled={saving} className="btn-ghost px-2 py-1.5 text-xs text-flux md:px-3 md:py-2">
                <Save className={`h-3.5 w-3.5 ${saving ? 'animate-spin' : ''}`} />
                <span className="hidden md:inline">{saving ? '保存中…' : '保存'}</span>
              </button>
            </>
          ) : (
            <>
              <button onClick={startEdit} className="btn-ghost px-2 py-1.5 text-xs md:px-3 md:py-2">
                <Pencil className="h-3.5 w-3.5" />
                <span className="hidden md:inline">编辑</span>
              </button>
              <button onClick={reprocess} disabled={reprocessing} className="btn-ghost px-2 py-1.5 text-xs md:px-3 md:py-2">
                <RefreshCw className={`h-3.5 w-3.5 ${reprocessing ? 'animate-spin' : ''}`} />
                <span className="hidden md:inline">{reprocessing ? '重新处理中…' : '重新 OCR'}</span>
              </button>
              <button
                onClick={() => deleteNote(false)}
                disabled={deleting}
                title="删除笔记（保留物理文件，由 Syncthing 管理）"
                className="btn-ghost px-2 py-1.5 text-xs text-dust hover:text-rose md:px-3 md:py-2"
              >
                <Trash2 className={`h-3.5 w-3.5 ${deleting ? 'animate-pulse' : ''}`} />
                <span className="hidden md:inline">{deleting ? '删除中…' : '删除'}</span>
              </button>
            </>
          )}
        </div>
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
        {note.manually_edited && (
          <button
            onClick={clearManualEdit}
            className="flex items-center gap-1 text-dust/70 hover:text-amber"
            title="清除人工编辑标记"
          >
            <RotateCcw className="h-3 w-3" />
            清除标记
          </button>
        )}
      </div>

      {/* 关键词（非编辑模式）/ 关键词输入（编辑模式） */}
      {!editing && note.keywords && note.keywords.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-white/5 px-3 py-2.5 md:px-6 md:py-3">
          <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-dust/60">关键词</span>
          {note.keywords.map((kw) => (
            <span key={kw} className="chip">{kw}</span>
          ))}
        </div>
      )}
      {editing && (
        <div className="flex items-center gap-2 border-b border-white/5 px-3 py-2.5 md:px-6 md:py-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-dust/60">关键词</span>
          <input
            value={editKeywords}
            onChange={(e) => setEditKeywords(e.target.value)}
            placeholder="逗号分隔，如：机器学习, 神经网络, 梯度下降"
            className="flex-1 bg-transparent text-sm text-starlight placeholder:text-dust/40 focus:outline-none"
          />
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
              {_renderOriginalFile(note)}
            </div>
          </div>
        </div>

        {/* OCR 文本 / 编辑区 */}
        <div className={cn('flex flex-col overflow-hidden', mobileTab !== 'ocr' && 'hidden lg:flex')}>
          <div className="flex items-center justify-between border-b border-white/5 px-3 py-2 md:px-6 md:py-2.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust/70">
              {editing ? '编辑 OCR 文本' : 'OCR 文本'}
            </span>
            {!editing && (
              <button
                onClick={copyOcr}
                disabled={!note.ocr_text}
                className="flex items-center gap-1.5 rounded-md border border-white/10 px-2 py-1 font-mono text-[10px] text-dust transition-colors hover:border-flux/30 hover:text-flux disabled:opacity-30"
              >
                {copied ? <Check className="h-3 w-3 text-flux" /> : <Copy className="h-3 w-3" />}
                {copied ? '已复制' : '复制'}
              </button>
            )}
          </div>

          {editing ? (
            /* 编辑模式：可编辑 title / summary / ocr_text */
            <div className="flex flex-1 flex-col gap-3 overflow-auto p-3 md:p-6">
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">标题</label>
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full rounded-md border border-white/10 bg-void-200/50 px-3 py-2 text-sm text-starlight focus:border-flux/40 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">摘要</label>
                <textarea
                  value={editSummary}
                  onChange={(e) => setEditSummary(e.target.value)}
                  rows={3}
                  className="w-full resize-y rounded-md border border-white/10 bg-void-200/50 px-3 py-2 text-sm text-starlight focus:border-flux/40 focus:outline-none"
                />
              </div>
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-wider text-dust/70">OCR 文本（Markdown）</label>
                  <button
                    type="button"
                    onClick={() => setEditPreview((v) => !v)}
                    className="rounded border border-white/10 px-2 py-0.5 font-mono text-[10px] text-dust hover:border-flux/30 hover:text-flux"
                  >
                    {editPreview ? '编辑' : '预览'}
                  </button>
                </div>
                {editPreview ? (
                  <div className="min-h-[300px] flex-1 overflow-auto rounded-md border border-white/10 bg-void-200/50 px-3 py-2">
                    <MarkdownView content={editOcrText} mermaidCode={editMermaid} noteFilePath={note.file_path} />
                  </div>
                ) : (
                  <textarea
                    value={editOcrText}
                    onChange={(e) => setEditOcrText(e.target.value)}
                    className="min-h-[300px] flex-1 resize-y rounded-md border border-white/10 bg-void-200/50 px-3 py-2 font-mono text-xs leading-relaxed text-starlight focus:border-flux/40 focus:outline-none md:text-sm"
                  />
                )}
              </div>
              <div>
                <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">
                  Mermaid 关系图代码（可选）
                </label>
                <textarea
                  value={editMermaid}
                  onChange={(e) => setEditMermaid(e.target.value)}
                  rows={4}
                  placeholder={"flowchart LR\n  A[问题] --> B[方案]"}
                  className="w-full resize-y rounded-md border border-white/10 bg-void-200/50 px-3 py-2 font-mono text-xs leading-relaxed text-starlight placeholder:text-dust/40 focus:border-flux/40 focus:outline-none"
                />
              </div>
              <div className="rounded-md border border-flux/10 bg-flux/[0.03] p-2 text-[11px] text-dust">
                保存后将标记为「已人工修正」，后续重新 OCR 不会覆盖你的修改。同时会自动重算向量与图谱链接。
              </div>
            </div>
          ) : (
            <div className="flex-1 overflow-auto p-3 md:p-6">
              {note.summary && (
                <div className="mb-4 rounded-lg border border-flux/10 bg-flux/[0.03] p-3 md:mb-5 md:p-4">
                  <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-flux/70">摘要</div>
                  <p className="text-sm leading-relaxed text-starlight/85">{note.summary}</p>
                </div>
              )}
              {note.ocr_text ? (
                <>
                  <MarkdownView content={note.ocr_text} mermaidCode={note.mermaid} noteFilePath={note.file_path} />
                </>
              ) : (
                <div className="rounded-lg border border-dashed border-white/10 px-4 py-8 text-center font-mono text-xs text-dust/50">
                  {note.status === 'done' ? '该笔记未提取到 OCR 文本' : '笔记尚未完成 OCR 处理'}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
