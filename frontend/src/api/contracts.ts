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

export interface ApiSourceSummary {
  id: number
  name: string
  source_type: string
  base_url: string
  allow_private_networks: boolean
  enabled: boolean
  created_at: string
}

export interface ToolSummary {
  id: number
  api_source_id: number
  operation_key: string
  name: string
  description: string | null
  input_schema: Record<string, unknown>
  enabled: boolean
}

export interface SourceImportResponse {
  source: ApiSourceSummary
  tools: ToolSummary[]
}

export interface ToolAuthConfig {
  id?: number
  enabled: boolean
  login_tool_id: number | null
  username_field: string
  password_field: string
  token_json_path: string | null
  expires_json_path: string | null
  auth_type: 'bearer' | 'header' | 'cookie' | 'query'
  auth_name: string
  auth_prefix: string
  idle_minutes: number
  absolute_hours: number
}
