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
  Plus,
  Star,
  Camera,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type AllSettings, type WatchFolder, type DiscoveredFolder, type SystemInfo, type SourceStat, type OcrModel } from '@/api/client'
import { useDeviceDetect } from '@/hooks/useDeviceDetect'
import { useAppStore } from '@/store'
import { cn, formatBytes } from '@/lib/utils'

type Tab = 'folders' | 'model' | 'ocr' | 'relay' | 'system'

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
          ['ocr', 'OCR 模型'],
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
            {tab === 'ocr' && <OcrModelsTab settings={settings} onChange={load} onFlash={flash} />}
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
  const [ocrModel, setOcrModel] = useState(settings.model.ocr_model)
  const [ocrBaseUrl, setOcrBaseUrl] = useState(settings.model.ocr_base_url)
  const [ocrApiKey, setOcrApiKey] = useState('')
  const [llmModel, setLlmModel] = useState(settings.model.llm_model)
  const [llmBaseUrl, setLlmBaseUrl] = useState(settings.model.llm_base_url)
  const [llmApiKey, setLlmApiKey] = useState('')
  const [qaModel, setQaModel] = useState(settings.model.qa_model ?? '')
  const [embeddingModel, setEmbeddingModel] = useState(settings.model.embedding_model)
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState(settings.model.embedding_base_url)
  const [embeddingApiKey, setEmbeddingApiKey] = useState('')
  const [embeddingDim, setEmbeddingDim] = useState(settings.model.embedding_dim)

  useEffect(() => {
    setOcrModel(settings.model.ocr_model)
    setOcrBaseUrl(settings.model.ocr_base_url)
    setOcrApiKey('')
    setLlmModel(settings.model.llm_model)
    setLlmBaseUrl(settings.model.llm_base_url)
    setLlmApiKey('')
    setQaModel(settings.model.qa_model ?? '')
    setEmbeddingModel(settings.model.embedding_model)
    setEmbeddingBaseUrl(settings.model.embedding_base_url)
    setEmbeddingApiKey('')
    setEmbeddingDim(settings.model.embedding_dim)
  }, [settings.model])

  const saveModel = () => {
    onSave({
      model: {
        ...settings.model,
        ocr_model: ocrModel,
        ocr_base_url: ocrBaseUrl,
        ocr_api_key: ocrApiKey || undefined,
        llm_model: llmModel,
        llm_base_url: llmBaseUrl,
        llm_api_key: llmApiKey || undefined,
        qa_model: qaModel,
        embedding_model: embeddingModel,
        embedding_base_url: embeddingBaseUrl,
        embedding_api_key: embeddingApiKey || undefined,
        embedding_dim: embeddingDim,
      },
    })
  }

  const field = (
    label: string,
    value: string | number,
    onChange: (value: string) => void,
    placeholder = '',
    type: 'text' | 'password' = 'text',
  ) => (
    <div>
      <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
      />
    </div>
  )

  return (
    <div className="max-w-2xl space-y-5">
      <div className="rounded-xl border border-azure/20 bg-azure/5 p-3 text-xs leading-relaxed text-dust">
        OCR、LLM 和 Embedding 支持三套不同的 OpenAI 兼容 API。API Key 只保存在本机数据库，
        保存后不会回显；留空表示保持原 Key 不变。
      </div>

      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Camera className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">OCR API</span>
        </div>
        <div className="space-y-3">
          {field('Base URL', ocrBaseUrl, setOcrBaseUrl, 'https://api.siliconflow.cn/v1')}
          {field('API Key', ocrApiKey, setOcrApiKey, settings.model.ocr_api_key_set ? '已配置，留空不变' : 'sk-...', 'password')}
          {field('视觉模型 ID', ocrModel, setOcrModel, 'Qwen/Qwen3-VL-32B-Instruct')}
        </div>
      </div>

      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Cpu className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">LLM API</span>
        </div>
        <div className="space-y-3">
          {field('Base URL', llmBaseUrl, setLlmBaseUrl, 'https://api.siliconflow.cn/v1')}
          {field('API Key', llmApiKey, setLlmApiKey, settings.model.llm_api_key_set ? '已配置，留空不变' : 'sk-...', 'password')}
          {field('通用 LLM 模型 ID', llmModel, setLlmModel, 'deepseek-ai/DeepSeek-V3.2')}
          {field('问答模型 ID（可选，默认用通用 LLM）', qaModel, setQaModel, 'deepseek-ai/DeepSeek-V3.2')}
        </div>
      </div>

      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <DbIcon className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">Embedding API</span>
        </div>
        <div className="space-y-3">
          {field('Base URL', embeddingBaseUrl, setEmbeddingBaseUrl, 'https://api.siliconflow.cn/v1')}
          {field('API Key', embeddingApiKey, setEmbeddingApiKey, settings.model.embedding_api_key_set ? '已配置，留空不变' : 'sk-...', 'password')}
          {field('Embedding 模型 ID', embeddingModel, setEmbeddingModel, 'BAAI/bge-m3')}
          {field('向量维度', embeddingDim, (value) => setEmbeddingDim(parseInt(value, 10) || 0), '1024')}
        </div>
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
        onClick={saveModel}
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
    ['gamma', 'γ 内容重合', '0.1'],
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
// OCR 模型管理（多模型配置 + primary + 启停）
// ===========================================================================
function OcrModelsTab({
  settings,
  onChange,
  onFlash,
}: {
  settings: AllSettings
  onChange: () => void
  onFlash: (m: string) => void
}) {
  const models = settings.ocr_models ?? []
  const [newName, setNewName] = useState('')
  const [newModel, setNewModel] = useState('')
  const [adding, setAdding] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const addModel = async () => {
    if (!newName.trim() || !newModel.trim()) {
      onFlash('请填写名称和模型 ID')
      return
    }
    setAdding(true)
    try {
      await api.addOcrModel({ name: newName.trim(), model: newModel.trim() })
      setNewName('')
      setNewModel('')
      onChange()
      onFlash('已添加 OCR 模型')
    } catch (e) {
      onFlash('添加失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setAdding(false)
    }
  }

  const setPrimary = async (m: OcrModel) => {
    setBusyId(m.id)
    try {
      await api.patchOcrModel(m.id, { is_primary: true })
      onChange()
      onFlash(`已设为主模型：${m.name}`)
    } catch (e) {
      onFlash('设置失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusyId(null)
    }
  }

  const toggleEnabled = async (m: OcrModel) => {
    setBusyId(m.id)
    try {
      await api.patchOcrModel(m.id, { enabled: !m.enabled })
      onChange()
    } catch (e) {
      onFlash('切换失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (m: OcrModel) => {
    if (models.length <= 1) {
      onFlash('至少保留一个 OCR 模型')
      return
    }
    if (!confirm(`确定删除「${m.name}」？`)) return
    setBusyId(m.id)
    try {
      await api.deleteOcrModel(m.id)
      onChange()
      onFlash('已删除')
    } catch (e) {
      onFlash('删除失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusyId(null)
    }
  }

  const updateName = async (m: OcrModel, name: string) => {
    if (!name.trim() || name === m.name) return
    setBusyId(m.id)
    try {
      await api.patchOcrModel(m.id, { name: name.trim() })
      onChange()
    } catch (e) {
      onFlash('更新失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusyId(null)
    }
  }

  const updateModel = async (m: OcrModel, model: string) => {
    if (!model.trim() || model === m.model) return
    setBusyId(m.id)
    try {
      await api.patchOcrModel(m.id, { model: model.trim() })
      onChange()
    } catch (e) {
      onFlash('更新失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      {/* 说明 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-2 flex items-center gap-2 text-dust">
          <Camera className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">多模型 OCR</span>
        </div>
        <p className="text-xs leading-relaxed text-dust">
          配置多个 OCR 模型，新笔记自动用<b className="text-flux">主模型</b>识别；
          失败时按启用顺序自动 <b className="text-flux">fallback</b> 到下一个。
          所有 OCR fallback 共用「模型配置」里的 OCR API 端点和 Key，可与其他模型使用不同服务。
          笔记详情页可用任意模型<i>重新 OCR</i> 对比效果。
        </p>
        <div className="mt-3 grid grid-cols-1 gap-1.5 text-[11px] text-dust/80 sm:grid-cols-2">
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
            <div className="font-mono text-[10px] text-dust/60">硅基流动 · 推荐</div>
            <div className="mt-0.5 text-flux">Qwen/Qwen3-VL-32B-Instruct</div>
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
            <div className="font-mono text-[10px] text-dust/60">硅基流动 · 推荐</div>
            <div className="mt-0.5 text-flux">Qwen/Qwen2.5-VL-32B-Instruct</div>
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
            <div className="font-mono text-[10px] text-dust/60">硅基流动 · Kimi</div>
            <div className="mt-0.5 text-flux">moonshot/kimi-2.6-vl</div>
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
            <div className="font-mono text-[10px] text-dust/60">硅基流动 · 豆包</div>
            <div className="mt-0.5 text-flux">doubao-vl-pro</div>
          </div>
        </div>
        <p className="mt-2 text-[10px] text-dust/60">
          具体可用模型名请到硅基流动控制台查看，不同账号开通的模型可能不同。
        </p>
      </div>

      {/* 百度智能云 OCR 配置 */}
      <BaiduOcrPanel onFlash={onFlash} />

      {/* 已配置模型列表 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center justify-between text-dust">
          <div className="flex items-center gap-2">
            <span className="text-sm">已配置 OCR 模型 ({models.length})</span>
          </div>
          <span className="font-mono text-[10px] text-dust/60">点击 ⭐ 设为主模型</span>
        </div>
        <div className="space-y-2">
          {models.map((m) => (
            <div
              key={m.id}
              className={cn(
                'rounded-xl border p-3 transition-all',
                m.is_primary
                  ? 'border-flux/40 bg-flux/5 shadow-[0_0_0_1px_rgba(34,211,238,0.15)]'
                  : 'border-white/5 bg-white/[0.02]',
                !m.enabled && 'opacity-50',
              )}
            >
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPrimary(m)}
                  disabled={busyId === m.id || m.is_primary}
                  title={m.is_primary ? '当前主模型' : '设为主模型'}
                  className="shrink-0 p-1"
                >
                  <Star
                    className={cn('h-4 w-4', m.is_primary ? 'fill-flux text-flux' : 'text-dust hover:text-flux')}
                    strokeWidth={1.5}
                  />
                </button>
                <input
                  defaultValue={m.name}
                  onBlur={(e) => updateName(m, e.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-sm text-starlight hover:border-white/10 focus:border-flux/40 focus:outline-none"
                  placeholder="模型名称"
                />
                {m.is_primary && (
                  <span className="chip text-[9px] text-flux">主</span>
                )}
                <button
                  onClick={() => toggleEnabled(m)}
                  disabled={busyId === m.id}
                  title={m.enabled ? '停用' : '启用'}
                  className="btn-ghost shrink-0 p-1.5"
                >
                  <Power className={cn('h-3.5 w-3.5', m.enabled ? 'text-flux' : 'text-dust')} />
                </button>
                <button
                  onClick={() => remove(m)}
                  disabled={busyId === m.id || models.length <= 1}
                  title="删除"
                  className="btn-ghost shrink-0 p-1.5 text-rose/70 hover:text-rose"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <input
                defaultValue={m.model}
                onBlur={(e) => updateModel(m, e.target.value)}
                className="mt-2 w-full rounded-md border border-white/10 bg-void-500/40 px-2 py-1.5 font-mono text-[11px] text-flux/90 focus:border-flux/40 focus:outline-none"
                placeholder="模型 ID，如 Qwen/Qwen3-VL-32B-Instruct"
              />
            </div>
          ))}
          {models.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-dust/50">
              暂无 OCR 模型，使用下方表单添加
            </div>
          )}
        </div>
      </div>

      {/* 添加新模型 */}
      <div className="glass-panel rounded-xl p-4">
        <div className="mb-3 flex items-center gap-2 text-dust">
          <Plus className="h-4 w-4" strokeWidth={1.5} />
          <span className="text-sm">添加新 OCR 模型</span>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">名称（自定义）</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="如 Kimi 2.6 / 豆包 VL"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-dust/70">模型 ID</label>
            <input
              value={newModel}
              onChange={(e) => setNewModel(e.target.value)}
              placeholder="如 moonshot/kimi-2.6-vl"
              className="w-full rounded-lg border border-white/10 bg-void-500/40 px-3 py-2.5 text-sm text-starlight placeholder:text-dust/50 focus:border-flux/40 focus:outline-none"
            />
          </div>
        </div>
        <button
          onClick={addModel}
          disabled={adding || !newName.trim() || !newModel.trim()}
          className="btn-ghost mt-3 w-full justify-center"
        >
          {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          添加模型
        </button>
      </div>
    </div>
  )
}

// ===========================================================================
// 百度智能云 OCR 配置面板
// ===========================================================================
function BaiduOcrPanel({ onFlash }: { onFlash: (msg: string) => void }) {
  const [apiKey, setApiKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  // 从后端拉当前配置
  useEffect(() => {
    api.getSystemInfo().then((info) => {
      // systemInfo 不直接含百度配置，从 /api/ocr-models 间接判断 baidu 是否存在
      api.listOcrModels().then((res) => {
        const baidu = res.models.find((m) => m.id === 'baidu')
        setEnabled(!!baidu?.enabled)
        setLoading(false)
      })
    }).catch(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      // 百度凭证通过 .env 配置，前端只能提示用户改 .env
      // 这里只更新 enabled 状态（通过 ocr-models 接口）
      onFlash('百度 OCR 凭证需在 .env 中配置（BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY）')
    } finally {
      setSaving(false)
    }
  }

  const testBaidu = async () => {
    setTesting(true)
    try {
      const res = await fetch('/api/ocr-models/baidu/test', { method: 'POST' })
      const data = await res.json()
      if (data.ok) {
        onFlash(`百度 OCR 连通正常，识别到 ${data.chars} 字符`)
      } else {
        onFlash(`百度 OCR 测试失败：${data.error || '未知错误'}`)
      }
    } catch (e) {
      onFlash(`测试请求失败：${e instanceof Error ? e.message : '未知'}`)
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <div className="glass-panel rounded-xl p-4">
        <Loader2 className="h-4 w-4 animate-spin text-dust" />
      </div>
    )
  }

  return (
    <div className="glass-panel rounded-xl border-azure/10 p-4">
      <div className="mb-2 flex items-center gap-2 text-dust">
        <Camera className="h-4 w-4 text-azure" strokeWidth={1.5} />
        <span className="text-sm">百度智能云 OCR（手写专用）</span>
        <span className="ml-auto rounded bg-azure/10 px-1.5 py-0.5 text-[10px] text-azure/80">
          {enabled ? '已启用' : '未启用'}
        </span>
      </div>
      <p className="text-xs leading-relaxed text-dust">
        百度手写文字识别接口，针对不规则手写字体优化，识别准确率 90%+，免费额度 500 次/天。
        配置后作为 OCR <b className="text-azure">优先候选</b>，失败时自动 fallback 到 Kimi K2.6。
      </p>

      <div className="mt-3 space-y-2 rounded-lg border border-white/5 bg-void-500/30 p-3">
        <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">配置方式</div>
        <p className="text-[11px] text-dust/80">
          1. 访问 <a href="https://console.bce.baidu.com/ai/#/ai/ocr/overview/index" target="_blank" rel="noreferrer" className="text-azure hover:underline">百度智能云 OCR 控制台</a>
          {' '}→ 创建应用 → 获取 API Key 和 Secret Key
        </p>
        <p className="text-[11px] text-dust/80">
          2. 编辑服务器 <code className="rounded bg-void-300/50 px-1 text-flux">~/brain/.env</code> 文件，填入：
        </p>
        <pre className="overflow-x-auto rounded bg-void-300/50 p-2 font-mono text-[10px] text-flux">
{`BAIDU_OCR_API_KEY=你的APIKey
BAIDU_OCR_SECRET_KEY=你的SecretKey
BAIDU_OCR_ENABLED=true`}
        </pre>
        <p className="text-[11px] text-dust/80">
          3. 重启 backend： <code className="rounded bg-void-300/50 px-1 text-flux">docker compose restart backend</code>
        </p>
        <p className="text-[11px] text-dust/80">
          4. 点击下方「重置模型列表」让百度 OCR 出现在模型列表，或调用 <code className="rounded bg-void-300/50 px-1 text-flux">curl -X POST http://localhost:8000/api/ocr-models/reset</code>
        </p>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={testBaidu}
          disabled={testing || !enabled}
          className="btn-ghost px-3 py-1.5 text-xs"
        >
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Camera className="h-3.5 w-3.5" />}
          测试连通
        </button>
        <a
          href="https://console.bce.baidu.com/ai/#/ai/ocr/overview/index"
          target="_blank"
          rel="noreferrer"
          className="btn-ghost px-3 py-1.5 text-xs"
        >
          申请百度 OCR ↗
        </a>
      </div>
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
            <InfoRow label="云盘占用" value={formatBytes(info.storage.cloud_bytes)} />
            <InfoRow label="数据库" value={formatBytes(info.storage.db_bytes)} />
            <InfoRow label="磁盘可用" value={formatBytes(info.storage.disk_free_bytes)} />
          </div>
          <div className="mt-3 truncate font-mono text-[10px] text-dust">{info.paths.cloud_root}</div>
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
