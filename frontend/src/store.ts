import { create } from 'zustand'
import { api, type Stats, type Health } from '@/api/client'

// 全局状态：统计信息 + 健康状态（OCR 是否启用）
interface AppState {
  stats: Stats | null
  health: Health | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export const useAppStore = create<AppState>((set) => ({
  stats: null,
  health: null,
  loading: false,
  error: null,
  refresh: async () => {
    set({ loading: true, error: null })
    try {
      const [stats, health] = await Promise.all([api.getStats(), api.getHealth()])
      set({ stats, health, loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : '加载失败', loading: false })
    }
  },
}))
