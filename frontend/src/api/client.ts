import type { ApiErrorEnvelope } from './contracts'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly params: Record<string, unknown> = {},
  ) {
    super(code)
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  csrfToken?: string | null,
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: T | ApiErrorEnvelope
  try {
    payload = (text ? JSON.parse(text) : {}) as T | ApiErrorEnvelope
  } catch {
    throw new ApiError(response.status, response.ok ? 'response.invalid_json' : `http.${response.status}`)
  }
  if (!response.ok) {
    const envelope = payload as ApiErrorEnvelope
    throw new ApiError(response.status, envelope.error?.code ?? `http.${response.status}`, envelope.error?.params)
  }
  return payload as T
}
