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
  if (init.body) headers.set('Content-Type', 'application/json')
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (response.status === 204) return undefined as T

  const payload = (await response.json()) as T | ApiErrorEnvelope
  if (!response.ok) {
    const envelope = payload as ApiErrorEnvelope
    throw new ApiError(response.status, envelope.error.code, envelope.error.params)
  }
  return payload as T
}
