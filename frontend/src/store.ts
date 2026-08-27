import { create } from 'zustand'
import { api, type Stats, type Health } from '@/api/client'

// 全局状态：统计信息 + 健康状态（OCR 是否启用）
interface AppState {
  stats: Stats | null
  health: Health | null
  loading: boolean
  error: string | null
  refreshing: boolean
  refresh: () => Promise<void>
}

export const useAppStore = create<AppState>((set) => ({
  stats: null,
  health: null,
  loading: false,
  error: null,
  refreshing: false,
  refresh: async () => {
    set({ loading: true, error: null })
    let failureMessage: string | null = null
    try {
      const [stats, health] = await Promise.all([api.getStats(), api.getHealth()])
      if (health?.data_mount && !health.data_mount.ready) {
        failureMessage = '数据库挂载自检未通过，正在等待 WSL 数据目录...'
        throw new Error(failureMessage)
      }
      set({ stats, health })
    } finally {
      set({
        loading: false,
        refreshing: false,
        ...(failureMessage ? { error: failureMessage } : {}),
      })
    }
    if (!failureMessage) {
      set({ error: null })
    }
  },
}))
