import { useEffect, useState } from 'react'

export type DeviceType = 'mobile' | 'tablet' | 'desktop'
export type DeviceOS = 'android' | 'ios' | 'windows' | 'mac' | 'linux' | 'unknown'

export interface DeviceInfo {
  /** 设备类型 */
  type: DeviceType
  /** 操作系统 */
  os: DeviceOS
  /** 是否触屏 */
  touch: boolean
  /** 屏幕宽度 */
  width: number
  /** 屏幕高度 */
  height: number
  /** 横屏 / 竖屏 */
  orientation: 'portrait' | 'landscape'
  /** 完整 UA（用于调试/上报） */
  userAgent: string
}

function detect(): DeviceInfo {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
  const w = typeof window !== 'undefined' ? window.innerWidth : 1280
  const h = typeof window !== 'undefined' ? window.innerHeight : 800

  // 操作系统识别
  let os: DeviceOS = 'unknown'
  const lower = ua.toLowerCase()
  if (lower.includes('android')) os = 'android'
  else if (/iphone|ipad|ipod/.test(lower)) os = 'ios'
  else if (lower.includes('windows')) os = 'windows'
  else if (lower.includes('mac')) os = 'mac'
  else if (lower.includes('linux')) os = 'linux'

  // 触屏
  const touch = typeof window !== 'undefined' && (('ontouchstart' in window) || navigator.maxTouchPoints > 0)

  // 设备类型：优先用 UA 判断移动端，再用宽度细分 tablet/desktop
  let type: DeviceType = 'desktop'
  const isMobileUA = /android|iphone|ipod|mobile|phone/i.test(lower)
  const isTabletUA = /ipad|tablet|silk/i.test(lower) || (os === 'ios' && lower.includes('mac') && touch)
  if (isMobileUA && !isTabletUA) type = 'mobile'
  else if (isTabletUA) type = 'tablet'
  else if (w < 768) type = 'mobile'
  else if (w < 1024) type = 'tablet'

  const orientation: 'portrait' | 'landscape' = h > w ? 'portrait' : 'landscape'

  return { type, os, touch, width: w, height: h, orientation, userAgent: ua }
}

/**
 * 自动识别当前设备，用于适配页面形状。
 *
 * - 移动端：底部 Tab、全屏 Sheet、触摸优化
 * - 平板：可折叠侧栏
 * - 桌面：三栏布局
 *
 * 监听 resize 事件实时更新，断点变化时触发重渲染。
 */
export function useDeviceDetect(): DeviceInfo {
  const [info, setInfo] = useState<DeviceInfo>(() => detect())

  useEffect(() => {
    const onChange = () => setInfo(detect())
    window.addEventListener('resize', onChange)
    window.addEventListener('orientationchange', onChange)
    return () => {
      window.removeEventListener('resize', onChange)
      window.removeEventListener('orientationchange', onChange)
    }
  }, [])

  return info
}
