import { useRef, useState } from 'react'
import { Camera, ImagePlus, FileText, FileCode2, Loader2, X, CheckCircle2, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/api/client'
import { useDeviceDetect } from '@/hooks/useDeviceDetect'

interface UploadResult {
  filename: string
  success: boolean
  error?: string
}

export function UploadButton({ onUploaded }: { onUploaded?: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const docInputRef = useRef<HTMLInputElement>(null)
  const mdInputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [results, setResults] = useState<UploadResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const device = useDeviceDetect()

  const handleFiles = async (files: FileList | null, app: string = 'camera') => {
    if (!files || files.length === 0) return
    setUploading(true)
    setError(null)
    setResults(null)
    try {
      const devName = device.type === 'mobile' || device.type === 'tablet'
        ? (device.os === 'ios' ? 'iphone' : 'android')
        : 'desktop'
      const res = await api.uploadNotes(
        Array.from(files),
        devName,
        app,
      )
      setResults(
        res.files.map((f) => ({
          filename: f.filename,
          success: f.success,
          error: f.error,
        })),
      )
      // 上传成功后通知父组件刷新
      if (res.success > 0 && onUploaded) {
        // 给 watcher 一点时间检测文件
        setTimeout(onUploaded, 1500)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
      // 清空 input 以便重复选择同一文件
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (cameraInputRef.current) cameraInputRef.current.value = ''
      if (docInputRef.current) docInputRef.current.value = ''
      if (mdInputRef.current) mdInputRef.current.value = ''
    }
  }

  return (
    <>
      {/* 触发按钮 */}
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-lg border border-flux/30 bg-flux/10 px-3 py-1.5 font-mono text-[11px] text-flux backdrop-blur-md transition-all hover:bg-flux/20 active:scale-95 md:px-3 md:py-2 md:text-xs"
        title="上传手写笔记"
      >
        <Camera className="h-3.5 w-3.5" strokeWidth={1.5} />
        <span>上传</span>
      </button>

      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,application/pdf,.pdf"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files, 'gallery')}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/png,image/jpeg"
        capture="environment"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files, 'camera')}
      />
      <input
        ref={docInputRef}
        type="file"
        accept=".txt,.md,.markdown,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files, 'document')}
      />
      <input
        ref={mdInputRef}
        type="file"
        accept=".md,.markdown,text/markdown,text/x-markdown"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files, 'markdown')}
      />

      {/* 上传面板 */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm md:items-center">
          <div className="w-full max-w-md rounded-t-2xl border border-white/10 bg-void-200 p-5 shadow-2xl md:rounded-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-display text-base text-starlight">上传笔记</h3>
              <button
                onClick={() => {
                  setOpen(false)
                  setResults(null)
                  setError(null)
                }}
                className="flex h-7 w-7 items-center justify-center rounded-md text-dust hover:bg-white/5 hover:text-starlight"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* 上传中 */}
            {uploading && (
              <div className="flex flex-col items-center gap-3 py-8">
                <Loader2 className="h-8 w-8 animate-spin text-flux" />
                <p className="font-mono text-xs text-dust">上传中…</p>
              </div>
            )}

            {/* 结果展示 */}
            {!uploading && results && (
              <div className="space-y-2">
                {results.map((r, i) => (
                  <div
                    key={i}
                    className={cn(
                      'flex items-start gap-2 rounded-lg border px-3 py-2',
                      r.success
                        ? 'border-flux/20 bg-flux/5'
                        : 'border-rose/20 bg-rose/5',
                    )}
                  >
                    {r.success ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-flux" />
                    ) : (
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-starlight">{r.filename}</div>
                      {r.error && <div className="mt-0.5 text-[10px] text-rose/80">{r.error}</div>}
                    </div>
                  </div>
                ))}
                <div className="rounded-lg bg-white/5 px-3 py-2 text-center text-[11px] text-dust">
                  文件已保存到私有云盘，正在自动处理（图片走 OCR，文档走文本抽取），约 10-30 秒后刷新可见
                </div>
                <button
                  onClick={() => {
                    setOpen(false)
                    setResults(null)
                  }}
                  className="w-full rounded-lg border border-white/10 bg-white/5 py-2 text-xs text-starlight hover:bg-white/10"
                >
                  完成
                </button>
              </div>
            )}

            {/* 错误展示 */}
            {!uploading && error && (
              <div className="space-y-3">
                <div className="rounded-lg border border-rose/20 bg-rose/5 px-3 py-2 text-xs text-rose">
                  {error}
                </div>
                <button
                  onClick={() => setError(null)}
                  className="w-full rounded-lg border border-white/10 bg-white/5 py-2 text-xs text-starlight hover:bg-white/10"
                >
                  重试
                </button>
              </div>
            )}

            {/* 选择上传方式 */}
            {!uploading && !results && !error && (
              <div className="space-y-2.5">
                <button
                  onClick={() => cameraInputRef.current?.click()}
                  className="flex w-full items-center gap-3 rounded-xl border border-flux/30 bg-flux/10 px-4 py-3.5 text-left transition-all hover:bg-flux/20 active:scale-[0.98]"
                >
                  <Camera className="h-5 w-5 text-flux" strokeWidth={1.5} />
                  <div>
                    <div className="text-sm text-starlight">拍照上传</div>
                    <div className="font-mono text-[10px] text-dust">调用摄像头拍摄手写笔记</div>
                  </div>
                </button>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex w-full items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5 text-left transition-all hover:bg-white/10 active:scale-[0.98]"
                >
                  <ImagePlus className="h-5 w-5 text-azure" strokeWidth={1.5} />
                  <div>
                    <div className="text-sm text-starlight">选择图片 / PDF</div>
                    <div className="font-mono text-[10px] text-dust">支持 PNG / JPG / PDF（走 OCR 识别）</div>
                  </div>
                </button>
                <button
                  onClick={() => docInputRef.current?.click()}
                  className="flex w-full items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5 text-left transition-all hover:bg-white/10 active:scale-[0.98]"
                >
                  <FileText className="h-5 w-5 text-amber" strokeWidth={1.5} />
                  <div>
                    <div className="text-sm text-starlight">上传文档</div>
                    <div className="font-mono text-[10px] text-dust">支持 TXT / Markdown / Word（.docx）</div>
                  </div>
                </button>
                <button
                  onClick={() => mdInputRef.current?.click()}
                  className="flex w-full items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5 text-left transition-all hover:bg-white/10 active:scale-[0.98]"
                >
                  <FileCode2 className="h-5 w-5 text-emerald-300" strokeWidth={1.5} />
                  <div>
                    <div className="text-sm text-starlight">上传 Markdown</div>
                    <div className="font-mono text-[10px] text-dust">支持 .md / .markdown，直接抽取正文，不走 OCR</div>
                  </div>
                </button>
                <div className="pt-2 text-center font-mono text-[10px] text-dust/70">
                  图片走 OCR · 文档 / Markdown 走文本抽取 · 单文件最大 50MB
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
