export class ApiError extends Error {
  status: number
  hint: string | null

  constructor(message: string, status = 0, hint: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.hint = hint
  }
}

interface ErrorDetail {
  message?: string
  hint?: string
  [key: string]: unknown
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
    })
  } catch (error) {
    throw new ApiError(
      `无法连接本地服务：${error instanceof Error ? error.message : String(error)}`,
      0,
      '先在终端运行 citationproof serve，再刷新页面。',
    )
  }
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    let hint: string | null = null
    try {
      const payload = (await response.json()) as { detail?: string | ErrorDetail }
      if (typeof payload.detail === 'string') {
        message = payload.detail
      } else if (payload.detail) {
        message = String(payload.detail.message ?? message)
        hint = payload.detail.hint ? String(payload.detail.hint) : null
      }
    } catch {
      // Non-JSON error bodies keep the HTTP fallback message.
    }
    throw new ApiError(message, response.status, hint)
  }
  return (await response.json()) as T
}

export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }
  return new ApiError(error instanceof Error ? error.message : String(error))
}
