import { cn } from '@/lib/utils'
import type { NoteStatus } from '@/api/client'

const STATUS_META: Record<NoteStatus, { label: string; dot: string; text: string }> = {
  done: { label: '已完成', dot: 'bg-flux', text: 'text-flux' },
  pending: { label: '待处理', dot: 'bg-amber', text: 'text-amber' },
  processing: { label: 'OCR 中', dot: 'bg-azure', text: 'text-azure' },
  failed: { label: '失败', dot: 'bg-rose', text: 'text-rose' },
}

export function StatusBadge({ status, className }: { status: NoteStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.pending
  return (
    <span className={cn('inline-flex items-center gap-1.5 font-mono text-[11px] tracking-wide', meta.text, className)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', meta.dot, status === 'processing' && 'animate-pulse')} />
      {meta.label}
    </span>
  )
}

export function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  // 2026-07-11 14:30
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function shortDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
