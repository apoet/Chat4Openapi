export type Locale = 'en-US' | 'zh-CN'

export interface SetupStatus {
  initialized: boolean
  locale: Locale | null
}

export interface SetupRequest {
  username: string
  password: string
  locale: Locale
}

export interface AdminSummary {
  username: string
  locale: Locale
}

export interface AuthResponse {
  admin: AdminSummary
  csrf_token: string
}

export interface ApiErrorEnvelope {
  error: {
    code: string
    params: Record<string, unknown>
  }
}
