import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Check,
  Cloud,
  Copy,
  ExternalLink,
  FolderOpen,
  HardDrive,
  Share2,
  Smartphone,
  Upload,
  Wifi,
} from 'lucide-react'
import { api, type AccessInfo, type SystemInfo } from '@/api/client'
import { cn, formatBytes } from '@/lib/utils'

function AddressRow({
  label,
  url,
  copiedKey,
  copied,
  onCopy,
}: {
  label: string
  url: string
  copiedKey: string
  copied: string
  onCopy: (text: string, key: string) => void
}) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] p-3">
      <div className="min-w-0 flex-1">
        <div className="mb-1 text-xs text-dust">{label}</div>
        <div className="truncate font-mono text-sm text-starlight">{url}</div>
      </div>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="btn-ghost shrink-0 px-2.5 py-1.5"
        aria-label={`打开 ${label}`}
      >
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
      <button
        onClick={() => onCopy(url, copiedKey)}
        className="btn-ghost shrink-0 px-2.5 py-1.5"
        aria-label={`复制 ${label}`}
      >
        {copied === copiedKey ? <Check className="h-3.5 w-3.5 text-flux" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

export default function Connect() {
  const [info, setInfo] = useState<AccessInfo | null>(null)
  const [sys, setSys] = useState<SystemInfo | null>(null)
  const [copied, setCopied] = useState('')

  const currentUrl = window.location.origin
  const hostname = window.location.hostname
  const isMdns = hostname === 'brain.local' || hostname.endsWith('.local')
  const isIp = /^(\d{1,3}\.){3}\d{1,3}$/.test(hostname) || hostname.includes(':')

  const copy = useCallback(async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      setTimeout(() => setCopied(''), 1800)
    } catch {
      setCopied('')
    }
  }, [])

  useEffect(() => {
    api.getAccessInfo().then(setInfo).catch(() => {})
    api.getSystemInfo().then(setSys).catch(() => {})
  }, [])

  const canShare = typeof navigator !== 'undefined' && !!navigator.share
  const share = async () => {
    try {
      await navigator.share({ title: 'Brain', url: currentUrl })
    } catch {
      // 用户取消分享时无需提示
    }
  }

  const cloudPath = info
    ? `${info.cloud.root}/${info.cloud.upload_subdir}/<设备>-<应用>/<日期>/`
    : sys
      ? `${sys.paths.cloud_root}/from-brain/<设备>-<应用>/<日期>/`
      : 'cloud/from-brain/<设备>-<应用>/<日期>/'

  return (
    <div className="flex h-full flex-col">
      <div className="safe-top border-b border-white/5 px-4 py-4 md:px-8 md:py-5">
        <div className="flex items-center gap-2.5">
          <Wifi className="h-4 w-4 text-flux" strokeWidth={1.5} />
          <h1 className="font-display text-lg text-starlight md:text-xl">连接与上传</h1>
        </div>
        <p className="mt-1 text-xs text-dust md:text-sm">手机和平板访问地址、云盘入口与笔记应用保存路径</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {/* 当前访问地址 */}
          <section className="glass-panel rounded-xl p-4">
            <div className="mb-3 flex items-center gap-2 text-dust">
              <Smartphone className="h-4 w-4 text-azure" strokeWidth={1.5} />
              <span className="text-sm">当前访问地址</span>
              <span
                className={cn(
                  'ml-auto rounded-full px-2 py-0.5 font-mono text-[10px]',
                  isMdns ? 'bg-flux/10 text-flux' : isIp ? 'bg-amber/10 text-amber' : 'bg-white/5 text-dust',
                )}
              >
                {isMdns ? 'mDNS 固定名' : isIp ? '当前局域网 IP' : hostname}
              </span>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-flux/20 bg-flux/5 p-3">
              <span className="min-w-0 flex-1 truncate font-mono text-sm text-starlight">{currentUrl}</span>
              <button onClick={() => copy(currentUrl, 'current')} className="btn-ghost shrink-0 px-2.5 py-1.5">
                {copied === 'current' ? <Check className="h-3.5 w-3.5 text-flux" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
              {canShare && (
                <button onClick={share} className="btn-ghost shrink-0 px-2.5 py-1.5">
                  <Share2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <p className="mt-3 text-xs leading-relaxed text-dust">
              手机与服务器连接同一个 Wi-Fi 时，地址栏显示的就是这台手机当前应使用的地址。
            </p>
          </section>

          {/* 固定地址 */}
          <section className="glass-panel rounded-xl p-4">
            <div className="mb-3 flex items-center gap-2 text-dust">
              <Wifi className="h-4 w-4 text-flux" strokeWidth={1.5} />
              <span className="text-sm">固定访问名</span>
            </div>
            <div className="space-y-2">
              <AddressRow
                label="Brain 主界面"
                url="http://brain.local:8080"
                copiedKey="brain"
                copied={copied}
                onCopy={copy}
              />
              <AddressRow
                label="私有云盘网页"
                url="http://brain.local:8090/web/client"
                copiedKey="cloud"
                copied={copied}
                onCopy={copy}
              />
            </div>
            <p className="mt-3 text-xs leading-relaxed text-dust">
              使用固定名后，物理机 IP 变化不需要重新查询。若手机打不开 brain.local，把上面的 brain.local 换成当前访问地址中的 IP。
            </p>
          </section>

          {/* 手机应用保存路径 */}
          <section className="glass-panel rounded-xl p-4">
            <div className="mb-3 flex items-center gap-2 text-dust">
              <FolderOpen className="h-4 w-4 text-amber" strokeWidth={1.5} />
              <span className="text-sm">笔记应用保存路径</span>
            </div>
            <div className="space-y-2">
              <div className="rounded-xl border border-flux/20 bg-flux/5 p-3">
                <div className="mb-1 flex items-center gap-2 text-sm text-starlight">
                  <Upload className="h-4 w-4 text-flux" strokeWidth={1.5} />
                  最省事：从 Brain 主界面直接上传
                </div>
                <p className="text-xs leading-relaxed text-dust">
                  在任意笔记应用中导出/分享，再回到 Brain 点右上角“上传”。文件会保存到私有云盘并自动入库，不用找应用内部路径。
                </p>
                <Link
                  to="/graph"
                  className="btn-ghost mt-2 w-full justify-center py-2 text-xs"
                >
                  去上传
                </Link>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="mb-1 flex items-center gap-2 text-sm text-starlight">
                  <Cloud className="h-4 w-4 text-azure" strokeWidth={1.5} />
                  云盘网页上传
                </div>
                <p className="text-xs leading-relaxed text-dust">
                  打开私有云盘网页后直接拖入文件，受支持的文件类型同样会自动进入 Brain 知识库。
                </p>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="mb-1 flex items-center gap-2 text-sm text-starlight">
                  <HardDrive className="h-4 w-4 text-amber" strokeWidth={1.5} />
                  应用内部路径查询
                </div>
                <p className="text-xs leading-relaxed text-dust">
                  GoodNotes、Notability、备忘录等应用导出时通常不显示完整路径；先在导出面板选择“存储到文件/相册”，再使用上方上传入口即可。
                  使用 Syncthing 时，可在设置页用“自动扫描”发现并监听手机应用目录。
                </p>
                <Link
                  to="/settings"
                  className="btn-ghost mt-2 w-full justify-center py-2 text-xs"
                >
                  打开监听文件夹设置
                </Link>
              </div>
            </div>
          </section>

          {/* 云盘存储位置 */}
          <section className="glass-panel rounded-xl p-4">
            <div className="mb-3 flex items-center gap-2 text-dust">
              <Cloud className="h-4 w-4 text-azure" strokeWidth={1.5} />
              <span className="text-sm">云盘存储位置</span>
            </div>
            <div className="space-y-2">
              <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2.5">
                <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-dust/70">上传落盘目录</div>
                <div className="break-all font-mono text-xs leading-relaxed text-starlight">{cloudPath}</div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
                <div className="rounded-lg bg-white/[0.02] px-3 py-2">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">云盘占用</div>
                  <div className="font-mono text-starlight">{sys ? formatBytes(sys.storage.cloud_bytes) : '—'}</div>
                </div>
                <div className="rounded-lg bg-white/[0.02] px-3 py-2">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">磁盘可用</div>
                  <div className="font-mono text-starlight">{sys ? formatBytes(sys.storage.disk_free_bytes) : '—'}</div>
                </div>
                <div className="col-span-2 rounded-lg bg-white/[0.02] px-3 py-2 md:col-span-1">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-dust/70">账号密码</div>
                  <div className="text-xs text-dust">保存在服务器 secrets 文件中</div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
