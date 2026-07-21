import { useEffect } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Network, MessagesSquare, NotebookPen, Sparkles, Settings as SettingsIcon, Layers } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store'

interface NavItemProps {
  to: string
  label: string
  icon: React.ReactNode
  mobile?: boolean
}

function NavItem({ to, label, icon, mobile }: NavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'group flex items-center transition-all',
          mobile
            ? cn(
                'flex-1 flex-col gap-1 rounded-lg py-1.5 text-[10px]',
                isActive ? 'text-flux' : 'text-dust',
              )
            : cn(
                'gap-3 rounded-lg px-3 py-2.5 text-sm',
                isActive
                  ? 'bg-flux/10 text-flux shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]'
                  : 'text-dust hover:bg-white/[0.04] hover:text-starlight',
              ),
        )
      }
    >
      {icon}
      <span className={cn('font-medium tracking-wide', mobile ? 'text-[10px]' : '')}>{label}</span>
    </NavLink>
  )
}

function StatRow({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-[11px] uppercase tracking-wider text-dust">{label}</span>
      <span className={cn('font-mono text-sm tabular-nums', accent ?? 'text-starlight')}>{value}</span>
    </div>
  )
}

// 移动端紧凑统计条（顶部一行）
function MobileStatBar() {
  const { stats, health } = useAppStore()
  const navigate = useNavigate()
  if (!stats) return null
  return (
    <div className="flex items-center gap-3 overflow-x-auto px-4 py-2 font-mono text-[11px] text-dust">
      <span className="whitespace-nowrap">
        笔记 <span className="text-starlight">{stats.notes_total}</span>
      </span>
      <span className="text-dust/30">·</span>
      <span className="whitespace-nowrap">
        链接 <span className="text-azure">{stats.links_total}</span>
      </span>
      <span className="text-dust/30">·</span>
      <span className="whitespace-nowrap">
        处理中 <span className={stats.notes_pending > 0 ? 'text-amber' : 'text-dust'}>{stats.notes_pending}</span>
      </span>
      <span className="ml-auto flex items-center gap-2 whitespace-nowrap">
        <span className="flex items-center gap-1">
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              health?.openai_configured ? 'bg-flux' : 'bg-amber',
            )}
          />
          {health?.openai_configured ? 'OCR' : 'Demo'}
        </span>
        <button
          onClick={() => navigate('/settings')}
          className="flex h-6 w-6 items-center justify-center rounded-md text-dust transition-colors hover:text-flux"
          aria-label="设置"
        >
          <SettingsIcon className="h-4 w-4" strokeWidth={1.5} />
        </button>
      </span>
    </div>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const { refresh } = useAppStore()
  const location = useLocation()

  useEffect(() => {
    refresh()
  }, [location.pathname, refresh])

  return (
    <div className="flex h-full w-full flex-col overflow-hidden md:flex-row">
      {/* 桌面端左侧导航 */}
      <DesktopSidebar />

      {/* 移动端顶部统计条 */}
      <div className="safe-top border-b border-white/5 bg-void-300/40 backdrop-blur-xl md:hidden">
        <MobileStatBar />
      </div>

      {/* 主内容区 */}
      <main className="relative flex-1 overflow-hidden">{children}</main>

      {/* 移动端底部 Tab 导航 */}
      <nav className="safe-bottom flex items-center gap-1 border-t border-white/5 bg-void-300/80 px-2 pb-1 pt-2 backdrop-blur-xl md:hidden">
        <NavItem to="/graph" label="图谱" icon={<Network className="h-5 w-5" strokeWidth={1.5} />} mobile />
        <NavItem to="/qa" label="问答" icon={<MessagesSquare className="h-5 w-5" strokeWidth={1.5} />} mobile />
        <NavItem to="/cards" label="卡片" icon={<Layers className="h-5 w-5" strokeWidth={1.5} />} mobile />
        <NavItem to="/notes" label="笔记" icon={<NotebookPen className="h-5 w-5" strokeWidth={1.5} />} mobile />
      </nav>
    </div>
  )
}

function DesktopSidebar() {
  const { stats, health, refresh } = useAppStore()
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-white/5 bg-void-300/40 backdrop-blur-xl md:flex">
      {/* Logo 区 */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="relative flex h-9 w-9 items-center justify-center">
          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-azure/30 to-flux/20 blur-md" />
          <Sparkles className="relative h-5 w-5 text-flux" strokeWidth={1.5} />
        </div>
        <div className="leading-tight">
          <div className="font-display text-lg font-semibold tracking-tight text-starlight">Brain</div>
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust">笔记知识星座</div>
        </div>
      </div>

      {/* 导航项 */}
      <nav className="mt-2 flex flex-col gap-1 px-3">
        <NavItem to="/graph" label="知识图谱" icon={<Network className="h-4 w-4" strokeWidth={1.5} />} />
        <NavItem to="/qa" label="智能问答" icon={<MessagesSquare className="h-4 w-4" strokeWidth={1.5} />} />
        <NavItem to="/cards" label="知识卡片" icon={<Layers className="h-4 w-4" strokeWidth={1.5} />} />
        <NavItem to="/notes" label="笔记浏览" icon={<NotebookPen className="h-4 w-4" strokeWidth={1.5} />} />
        <NavItem to="/settings" label="设置" icon={<SettingsIcon className="h-4 w-4" strokeWidth={1.5} />} />
      </nav>

      <div className="mx-3 mt-6 h-px bg-gradient-to-r from-transparent via-white/8 to-transparent" />

      {/* 统计区 */}
      <div className="mt-4 flex-1 space-y-3 overflow-y-auto px-5">
        <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-dust/70">知识库状态</div>
        {stats ? (
          <div className="space-y-2.5">
            <StatRow label="笔记" value={stats.notes_total} accent="text-starlight" />
            <StatRow label="已处理" value={stats.notes_done} accent="text-flux" />
            <StatRow
              label="处理中"
              value={stats.notes_pending}
              accent={stats.notes_pending > 0 ? 'text-amber' : 'text-dust'}
            />
            <StatRow label="候选链接" value={stats.links_total} accent="text-azure" />
            <StatRow label="问答记录" value={stats.qa_total} accent="text-starlight" />
          </div>
        ) : (
          <div className="space-y-2.5">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-4 animate-pulse rounded bg-white/5" />
            ))}
          </div>
        )}
      </div>

      {/* 底部 OCR 状态 */}
      <div className="border-t border-white/5 px-5 py-4">
        <button
          onClick={refresh}
          className="flex w-full items-center gap-2 text-left"
        >
          <span
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              health?.openai_configured ? 'bg-flux shadow-[0_0_8px_rgba(34,211,238,0.7)]' : 'bg-amber shadow-[0_0_8px_rgba(245,166,35,0.5)]',
            )}
          />
          <div className="leading-tight">
            <div className="font-mono text-[11px] text-starlight/80">
              {health?.openai_configured ? 'OCR 已启用' : 'Demo 模式'}
            </div>
            <div className="font-mono text-[10px] text-dust">{health?.llm_model ?? '—'}</div>
          </div>
        </button>
      </div>
    </aside>
  )
}
