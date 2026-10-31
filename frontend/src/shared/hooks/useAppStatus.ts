import { useCallback, useEffect, useState } from 'react'
import { asApiError, getConfig, getHealth, type ApiError } from '../api'
import type { AppConfig, Health } from '../types'

export function useAppStatus() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const refresh = useCallback(() => {
    Promise.all([getConfig(), getHealth()])
      .then(([configPayload, healthPayload]) => {
        setConfig(configPayload)
        setHealth(healthPayload)
        setError(null)
      })
      .catch((cause) => setError(asApiError(cause)))
  }, [])

  useEffect(() => {
    refresh()
    const timer = window.setInterval(refresh, 60_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const checks = health?.checks ?? []
  const environmentState = error
    ? 'bad'
    : health === null
      ? 'wait'
      : health.ok
        ? 'ok'
        : 'bad'
  const environmentLabel = error
    ? '服务未连接'
    : health === null
      ? '检查中'
      : health.ok
        ? '环境正常'
        : '环境异常'
  const environmentDetail = checks.length
    ? checks.map((check) => `${check.name} ${check.ok ? '通过' : '失败'}`).join(' · ')
    : error?.message ?? '正在读取本地服务状态'

  return {
    config,
    health,
    error,
    refresh,
    checks,
    environmentState,
    environmentLabel,
    environmentDetail,
  }
}
