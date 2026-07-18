import { useCallback, useEffect, useState } from 'react'
import {
  Settings as SettingsIcon,
  FolderPlus,
  Search,
  Trash2,
  Power,
  Check,
  Loader2,
  RefreshCw,
  Database as DbIcon,
  HardDrive,
  Cpu,
  Cloud,
  Monitor,
  Smartphone,
  Zap,
  AlertTriangle,
  ChevronRight,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type AllSettings, type WatchFolder, type DiscoveredFolder, type SystemInfo, type SourceStat } from '@/api/client'
import { useDeviceDetect } from '@/hooks/useDeviceDetect'
import { useAppStore } from '@/store'
import { cn, formatBytes } from '@/lib/utils'

type Tab = 'folders' | 'model' | 'relay' | 'system'

export default function Settings() {
  const [tab, setTab] = useState<Tab>('folders')
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const device = useDeviceDetect()
  const { refresh: refreshStats } = useAppStore()

  const load = useCallback(() => {
    setLoading(true)
    api.getSettings().then(setSettings).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const flash = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const savePartial = async (patch: Partial<AllSettings>) => {
    setSaving(true)
    try {
      const updated = await api.updateSettings(patch)
      setSettings(updated)
      refreshStats()
      flash('已保存')
    } catch (e) {
      flash('保存失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部 */}
      <div className="safe-top border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="flex items-center gap-2.5">
          <SettingsIcon className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-lg text-starlight md:text-xl">设置</h1>
        </div>
        <p className="mt-1 text-xs text-dust md:text-sm">配置监听文件夹、模型、中继器位置与维护操作</p>
      </div>

      {/* Tab 切换（移动端可横滚） */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-white/5 px-4 py-2 md:px-8">
        {([
          ['folders', '监听文件夹'],
          ['model', '模型配置'],
          ['relay', '中继器位置'],
          ['system', '系统维护'],
        ] as [Tab, string][]).map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              'shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors',
              tab === t ? 'bg-flux/10 text-flux' : 'text-dust hover:bg-white/[0.04] hover:text-starlight',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-6">
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded-xl border border-white/5 bg-white/[0.02]" />
            ))}
          </div>
        ) : settings ? (
          <>
            {tab === 'folders' && <FoldersTab settings={settings} onChange={load} onFlash={flash} />}
            {tab === 'model' && <ModelTab settings={settings} onSave={savePartial} saving={saving} />}
            {tab === 'relay' && <RelayTab settings={settings} onSave={savePartial} saving={saving} />}
            {tab === 'system' && <SystemTab device={device} onFlash={flash} />}
          </>
        ) : (
          <div className="text-sm text-dust">加载失败</div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="safe-bottom fixed inset-x-0 bottom-16 z-50 mx-auto w-fit max-w-[90%] rounded-lg border border-flux/30 bg-void-300/95 px-4 py-2 text-sm text-flux shadow-panel backdrop-blur-md md:bottom-6">
          <Check className="mr-1.5 inline h-3.5 w-3.5" />
          {toast}
        </div>
      )}
    </div>
  )
}

// ===========================================================================
// 监听文件夹：手动添加 + 自动扫描
// ===========================================================================
function FoldersTab({
  settings,
  onChange,
  onFlash,
}: {
  settings: AllSettings
  onChange: () => void
  onFlash: (m: string) => void
}) {
  const [mode, setMode] = useState<'manual' | 'scan'>('manual')
  const [newPath, setNewPath] = useState('')
  const [newDevice, setNewDevice] = useState('')
  const [newApp, setNewApp] = useState('')
  const [adding, setAdding] = useState(false)

  const [scanRoot, setScanRoot] = useState('')
  const [scanning, setScanning] = useState(false)
  const [discovered, setDiscovered] = useState<DiscoveredFolder[]>([])

  const addFolder = async () => {
    if (!newPath.trim()) return
    setAdding(true)
    try {
      await api.addFolder({ path: newPath.trim(), device: newDevice || '自定义设备', app: newApp || '自定义应用' })
      setNewPath('')
      setNewDevice('')
      setNewApp('')
      onChange()
      onFlash('已添加并生效')
    } catch (e) {
      onFlash('添加失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setAdding(false)
    }
  }

  const doScan = async () => {
    if (!scanRoot.trim()) return
    setScanning(true)
    try {
      const res = await api.scanFolders(scanRoot.trim())
      setDiscovered(res.discovered)
      onFlash(`发现 ${res.total} 个候选文件夹`)
    } catch (e) {
      onFlash('扫描失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setScanning(false)
    }
  }

  const addDiscovered = async (d: DiscoveredFolder) => {
    try {
      await api.addFolder({ path: d.path, device: d.suggested_device, app: d.suggested_app })
      onChange()
      onFlash(`已添加 ${d.name}`)
    } catch (e) {
      onFlash('添加失败')
    }
  }

  const toggle = async (f: WatchFolder) => {
    await api.patchFolder(f.id, { enabled: !f.enabled })
    onChange()
  }

  const remove = async (f: WatchFolder) => {
    if (!confirm(`确定移除「${f.path}」？磁盘文件不会被删除。`)) return
    await api.deleteFolder(f.id)
    onChange()
    onFlash('已移除')
  }

  return (
    <div className="space-y-5">
      {/* 模式切换 */}
      <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.02] p-1">
        <button
          onClick={() => setMode('manual')}
          className={cn('rounded-md px-4 py-1.5 text-sm transition-colors', mode === 'manual' ? 'bg-flux/15 text-flux' : 'text-dust')}
        >
          手动添加
        </button>
        <button
          onClick={() => setMode('scan')}
          className={cn('rounded-md px-4 py-1.5 text-sm transition-colors', mode === 'scan' ? 'bg-flux/15 text-flux' : 'text-dust')}
        >
          自动扫描
        </button>
      </div>

      {/* 手动添加表单 */}
      {mode === 'manual' && (
        <div className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-center gap-2 text-dust">
            <FolderPlus className="h-4 w-4" strokeWidth={1.5} />
            <span className="text-sm">手动指定笔记文件夹路径</span>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="md:col-span-3">
              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">文件夹路径</label>
              <input
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                placeholder="如 /home/user/Sync/ipad-goodnotes"
                className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">设备标签</label>
              <input
                value={newDevice}
                onChange={(e) => setNewDevice(e.target.value)}
                placeholder="iPad"
                className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">应用标签</label>
              <input
                value={newApp}
                onChange={(e) => setNewApp(e.target.value)}
                placeholder="GoodNotes"
                className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
              />
            </div>
            <div className="flex items-end">
              <button onClick={addFolder} disabled={adding || !newPath.trim()} className="btn-ghost w-full justify-center disabled:opacity-40">
                {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
                添加并监听
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 自动扫描 */}
      {mode === 'scan' && (
        <div className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-center gap-2 text-dust">
            <Search className="h-4 w-4" strokeWidth={1.5} />
            <span className="text-sm">扫描根目录，自动发现含笔记文件的子文件夹</span>
          </div>
          <div className="flex gap-2">
            <input
              value={scanRoot}
              onChange={(e) => setScanRoot(e.target.value)}
              placeholder="如 /home/user/Sync（Syncthing 同步根目录）"
              className="flex-1 rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
            <button onClick={doScan} disabled={scanning || !scanRoot.trim()} className="btn-ghost justify-center disabled:opacity-40">
              {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              扫描
            </button>
          </div>

          {discovered.length > 0 && (
            <div className="mt-4 space-y-2">
              <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">
                发现 {discovered.length} 个候选文件夹
              </div>
              {discovered.map((d) => (
                <div key={d.path} className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] p-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-starlight">{d.name}</div>
                    <div className="mt-0.5 truncate font-mono text-[11px] text-dust">{d.path}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="chip">{d.file_count} 个笔记文件</span>
                      <span className="chip text-flux">{d.suggested_device} · {d.suggested_app}</span>
                    </div>
                  </div>
                  <button onClick={() => addDiscovered(d)} className="btn-ghost shrink-0 px-2 py-1.5 text-xs">
                    <ChevronRight className="h-3.5 w-3.5" />
                    添加
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 已配置文件夹列表 */}
      <div>
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-dust/70">
          已配置文件夹 ({settings.watch_folders.length})
        </div>
        <div className="space-y-2">
          {settings.watch_folders.map((f) => (
            <div key={f.id} className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className={cn('h-2 w-2 shrink-0 rounded-full', f.enabled ? 'bg-flux shadow-[0_0_6px_rgba(34,211,238,0.6)]' : 'bg-dust/40')} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm text-starlight">{f.device} · {f.app}</span>
                  {f.auto && <span className="chip text-[9px]">自动</span>}
                </div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-dust">{f.path}</div>
              </div>
              <button onClick={() => toggle(f)} title={f.enabled ? '停用' : '启用'} className="btn-ghost p-1.5">
                <Power className={cn('h-3.5 w-3.5', f.enabled ? 'text-flux' : 'text-dust')} />
              </button>
              <button onClick={() => remove(f)} title="移除" className="btn-ghost p-1.5 text-rose/70 hover:text-rose">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {settings.watch_folders.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-dust/50">
              暂无监听文件夹，使用上方表单添加
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// 模型配置
// ===========================================================================
function ModelTab({
  settings,
  onSave,
  saving,
}: {
  settings: AllSettings
  onSave: (patch: Partial<AllSettings>) => void
  saving: boolean
}) {
  const [llmModel, setLlmModel] = useState(settings.model.llm_model)
  const [embeddingModel, setEmbeddingModel] = useState(settings.model.embedding_model)
  const [baseUrl, setBaseUrl] = useState(settings.model.openai_base_url)

  useEffect(() => {
    setLlmModel(settings.model.llm_model)
    setEmbeddingModel(settings.model.embedding_model)
    setBaseUrl(settings.model.openai_base_url)
  }, [settings.model])

  return (
    <div className="max-w-2xl space-y-5">
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Cpu className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">LLM 与 OCR 模型</span>
        </div>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">视觉 OCR / 对话模型</label>
            <input
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder="gpt-4o"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">Embedding 模型</label>
            <input
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="text-embedding-3-small"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">OpenAI 兼容端点（可选）</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* API Key 状态 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-2 flex items-center gap-2">
          <span className={cn('h-2 w-2 rounded-full', settings.model.openai_api_key_set ? 'bg-flux' : 'bg-amber')} />
          <span className="text-sm text-starlight">
            {settings.model.openai_api_key_set ? 'API Key 已配置（通过环境变量 OPENAI_API_KEY）' : '未配置 API Key · 当前为 Demo 模式'}
          </span>
        </div>
        <p className="text-xs leading-relaxed text-dust">
          出于安全考虑，API Key 不在此页面配置，请在中继机的 <code className="rounded bg-white/5 px-1 font-mono">.env</code> 文件或环境变量中设置
          <code className="ml-1 rounded bg-white/5 px-1 font-mono">OPENAI_API_KEY</code>，重启后端生效。
        </p>
      </div>

      {/* 链接权重参数 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Zap className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">候选链接权重参数</span>
        </div>
        <LinkParamsEditor
          params={settings.link_params}
          onChange={(p) => onSave({ link_params: p })}
          saving={saving}
        />
      </div>

      <button
        onClick={() => onSave({ model: { ...settings.model, llm_model: llmModel, embedding_model: embeddingModel, openai_base_url: baseUrl } })}
        disabled={saving}
        className="btn-ghost w-full justify-center"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
        保存模型配置
      </button>
    </div>
  )
}

function LinkParamsEditor({
  params,
  onChange,
  saving,
}: {
  params: AllSettings['link_params']
  onChange: (p: AllSettings['link_params']) => void
  saving: boolean
}) {
  const [local, setLocal] = useState(params)
  useEffect(() => setLocal(params), [params])
  const fields: [keyof AllSettings['link_params'], string, string][] = [
    ['alpha', 'α 语义相似', '0.6'],
    ['beta', 'β 关键词重合', '0.3'],
    ['gamma', 'γ 时间衰减', '0.1'],
    ['threshold', '入图阈值', '0.35'],
  ]
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {fields.map(([key, label, ph]) => (
          <div key={key}>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">{label}</label>
            <input
              type="number"
              step="0.05"
              value={local[key]}
              onChange={(e) => setLocal({ ...local, [key]: parseFloat(e.target.value) || 0 })}
              placeholder={ph}
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
        ))}
      </div>
      <button onClick={() => onChange(local)} disabled={saving} className="btn-ghost px-3 py-1.5 text-xs">
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        应用链接参数
      </button>
    </div>
  )
}

// ===========================================================================
// 中继器位置：本地 PC（当前）/ 云端（预留）
// ===========================================================================
function RelayTab({
  settings,
  onSave,
  saving,
}: {
  settings: AllSettings
  onSave: (patch: Partial<AllSettings>) => void
  saving: boolean
}) {
  const relay = settings.relay
  const [info, setInfo] = useState<SystemInfo | null>(null)

  useEffect(() => {
    api.getSystemInfo().then(setInfo).catch(() => {})
  }, [])

  return (
    <div className="max-w-2xl space-y-5">
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Cloud className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">中继器部署位置</span>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/* 本地 PC */}
          <button
            onClick={() => onSave({ relay: { ...relay, location: 'local' } })}
            className={cn(
              'flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all',
              relay.location === 'local'
                ? 'border-flux/50 bg-flux/10 shadow-glow'
                : 'border-white/10 bg-white/[0.02] hover:border-white/20',
            )}
          >
            <Monitor className={cn('h-5 w-5', relay.location === 'local' ? 'text-flux' : 'text-dust')} strokeWidth={1.5} />
            <div>
              <div className="text-sm font-medium text-starlight">本地 PC</div>
              <div className="mt-0.5 text-xs text-dust">中继器跑在本地电脑，局域网访问 · 当前阶段推荐</div>
            </div>
            {relay.location === 'local' && (
              <span className="mt-1 rounded-full bg-flux/15 px-2 py-0.5 font-mono text-[10px] text-flux">当前</span>
            )}
          </button>

          {/* 云端（预留） */}
          <button
            onClick={() => onSave({ relay: { ...relay, location: 'cloud' } })}
            disabled
            className={cn(
              'relative flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all',
              relay.location === 'cloud'
                ? 'border-amber/50 bg-amber/10'
                : 'border-white/10 bg-white/[0.02] opacity-60',
            )}
          >
            <Cloud className={cn('h-5 w-5', relay.location === 'cloud' ? 'text-amber' : 'text-dust')} strokeWidth={1.5} />
            <div>
              <div className="text-sm font-medium text-starlight">云端服务器</div>
              <div className="mt-0.5 text-xs text-dust">后续上云端，公网可访问 · 开发中</div>
            </div>
            <span className="absolute right-3 top-3 rounded-full bg-white/5 px-2 py-0.5 font-mono text-[10px] text-dust">即将推出</span>
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">监听地址</label>
            <input
              value={relay.host}
              onChange={(e) => onSave({ relay: { ...relay, host: e.target.value } })}
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2 text-sm text-starlight focus:border-flux/40 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">端口</label>
            <input
              type="number"
              value={relay.port}
              onChange={(e) => onSave({ relay: { ...relay, port: parseInt(e.target.value) || 8000 } })}
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2 text-sm text-starlight focus:border-flux/40 focus:outline-none"
            />
          </div>
        </div>
        <p className="mt-3 text-xs text-dust">{relay.note}</p>
      </div>

      {/* 中继器环境信息 */}
      {info && (
        <div className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-center gap-2 text-dust">
            <HardDrive className="h-4 w-4" strokeWidth={1.5} />
            <span className="text-sm">中继器运行环境</span>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <InfoRow label="操作系统" value={`${info.platform.system} ${info.platform.release}`} />
            <InfoRow label="架构" value={info.platform.machine} />
            <InfoRow label="Python" value={info.platform.python} />
            <InfoRow label="监听文件夹" value={`${info.watch_folders_count} 个`} />
            <InfoRow label="笔记目录占用" value={formatBytes(info.storage.notes_bytes)} />
            <InfoRow label="数据库大小" value={formatBytes(info.storage.db_bytes)} />
            <InfoRow label="磁盘可用" value={formatBytes(info.storage.disk_free_bytes)} />
            <InfoRow label="磁盘总量" value={formatBytes(info.storage.disk_total_bytes)} />
          </div>
        </div>
      )}
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
      <span className="font-mono text-[11px] text-dust">{label}</span>
      <span className="text-sm text-starlight">{value}</span>
    </div>
  )
}

// ===========================================================================
// 系统维护
// ===========================================================================
function SystemTab({ device, onFlash }: { device: ReturnType<typeof useDeviceDetect>; onFlash: (m: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [sources, setSources] = useState<SourceStat[]>([])

  const load = () => {
    api.getSystemInfo().then(setInfo).catch(() => {})
    api.getSources().then((r) => setSources(r.sources)).catch(() => {})
  }
  useEffect(load, [])

  const run = async (key: string, fn: () => Promise<{ [k: string]: unknown }>) => {
    setBusy(key)
    try {
      const res = await fn()
      const msg = Object.entries(res)
        .filter(([k]) => k !== 'scanned' && k !== 'rebuilt' && k !== 'retried' && k !== 'vacuumed' && k !== 'reprocessed')
        .map(([k, v]) => `${k}: ${v}`)
        .join(' · ')
      onFlash(msg || '完成')
      load()
    } catch (e) {
      onFlash('失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusy(null)
    }
  }

  const osIcon = device.os === 'android' || device.os === 'ios' ? Smartphone : Monitor
  const OsIcon = osIcon

  return (
    <div className="max-w-2xl space-y-5">
      {/* 当前访问设备识别 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Smartphone className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">当前访问设备（自动识别）</span>
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <InfoRow label="设备类型" value={device.type === 'mobile' ? '手机' : device.type === 'tablet' ? '平板' : '桌面'} />
          <InfoRow label="系统" value={device.os} />
          <InfoRow label="触屏" value={device.touch ? '是' : '否'} />
          <InfoRow label="屏幕" value={`${device.width}×${device.height}`} />
        </div>
        <p className="mt-3 text-xs text-dust">
          页面已根据设备类型自动适配：{device.type === 'mobile' ? '底部 Tab + 全屏 Sheet' : device.type === 'tablet' ? '可折叠侧栏' : '三栏布局'}
        </p>
      </div>

      {/* 中继器环境 */}
      {info && (
        <div className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-center gap-2 text-dust">
            <OsIcon className="h-4 w-4" strokeWidth={1.5} />
            <span className="text-sm">中继器环境</span>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
            <InfoRow label="系统" value={`${info.platform.system} ${info.platform.release}`} />
            <InfoRow label="Python" value={info.platform.python} />
            <InfoRow label="监听文件夹" value={`${info.watch_folders_count} 个`} />
            <InfoRow label="笔记占用" value={formatBytes(info.storage.notes_bytes)} />
            <InfoRow label="数据库" value={formatBytes(info.storage.db_bytes)} />
            <InfoRow label="磁盘可用" value={formatBytes(info.storage.disk_free_bytes)} />
          </div>
        </div>
      )}

      {/* 来源分布 */}
      {sources.length > 0 && (
        <div className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-center gap-2 text-dust">
            <DbIcon className="h-4 w-4" strokeWidth={1.5} />
            <span className="text-sm">已入库笔记来源分布</span>
          </div>
          <div className="space-y-2">
            {sources.map((s, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-sm">
                <span className="text-starlight">{s.device ?? '—'} · {s.app ?? '—'}</span>
                <span className="font-mono text-flux">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 维护操作 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">维护操作</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <MaintBtn
            label="立即全量扫描"
            desc="手动触发一次文件夹扫描（不等凌晨 3 点）"
            icon={<Search className="h-4 w-4" />}
            busy={busy === 'scan'}
            onClick={() => run('scan', () => api.triggerScan() as Promise<{ [k: string]: unknown }>)}
          />
          <MaintBtn
            label="重建全部链接"
            desc="按当前权重参数重新计算所有候选链接"
            icon={<Zap className="h-4 w-4" />}
            busy={busy === 'rebuild'}
            onClick={() => run('rebuild', () => api.rebuildLinks() as Promise<{ [k: string]: unknown }>)}
          />
          <MaintBtn
            label="重试失败笔记"
            desc="把 failed 状态的笔记重新入队处理"
            icon={<AlertTriangle className="h-4 w-4" />}
            busy={busy === 'retry'}
            onClick={() => run('retry', () => api.retryFailed() as Promise<{ [k: string]: unknown }>)}
          />
          <MaintBtn
            label="压缩数据库"
            desc="VACUUM 回收 SQLite 空间"
            icon={<DbIcon className="h-4 w-4" />}
            busy={busy === 'vacuum'}
            onClick={() => run('vacuum', () => api.vacuumDb() as Promise<{ [k: string]: unknown }>)}
          />
        </div>

        <div className="mt-3 rounded-lg border border-amber/20 bg-amber/5 p-3">
          <div className="mb-2 flex items-center gap-2 text-amber">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span className="font-mono text-[11px] uppercase tracking-wider">危险操作</span>
          </div>
          <button
            onClick={() => {
              if (!confirm('确定对全部已完成笔记重新 OCR？这将消耗大量 API 调用，且处理期间图谱会临时变化。')) return
              run('reprocess', () => api.reprocessAll() as Promise<{ [k: string]: unknown }>)
            }}
            disabled={busy !== null}
            className="btn-ghost w-full justify-center border-rose/20 text-rose/80 hover:border-rose/40 hover:text-rose"
          >
            {busy === 'reprocess' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            全部重新 OCR（更换模型后使用）
          </button>
        </div>
      </div>

      {/* 开发与未来功能入口 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <ChevronRight className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">开发与扩展</span>
        </div>
        <p className="text-xs leading-relaxed text-dust">
          所有设置通过 <code className="rounded bg-white/5 px-1 font-mono">/api/settings</code> 持久化，维护接口位于
          <code className="ml-1 rounded bg-white/5 px-1 font-mono">/api/system/*</code>。新增功能可直接基于这些接口扩展，
          无需重启即可调整监听文件夹与模型参数。
        </p>
        <div className="mt-3">
          <Link to="/graph" className="btn-ghost text-xs">返回图谱 →</Link>
        </div>
      </div>
    </div>
  )
}

function MaintBtn({
  label,
  desc,
  icon,
  busy,
  onClick,
}: {
  label: string
  desc: string
  icon: React.ReactNode
  busy: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="flex items-start gap-3 rounded-lg border border-white/5 bg-white/[0.02] p-3 text-left transition-all hover:border-flux/30 hover:bg-flux/5 disabled:opacity-50"
    >
      <span className="mt-0.5 text-flux">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}</span>
      <div className="min-w-0">
        <div className="text-sm text-starlight">{label}</div>
        <div className="mt-0.5 text-xs text-dust">{desc}</div>
      </div>
    </button>
  )
}
