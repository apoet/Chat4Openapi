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
  document_url: string | null
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
  execution_schema: Record<string, unknown>
  tags: string[]
  enabled: boolean
}

export interface ToolParameterOverrideWrite {
  description: string | null
  example: unknown | null
}

export interface SourceImportResponse {
  source: ApiSourceSummary
  tools: ToolSummary[]
}

export interface SourceRefreshResult {
  created: number
  updated: number
  unchanged: number
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

export interface LlmProviderSummary {
  id: number
  name: string
  provider_type: 'openai' | 'anthropic'
  base_url: string
  default_model: string
  enabled: boolean
  has_api_key: boolean
}

export interface AgentConfig {
  id: number
  name: string
  enabled: boolean
  is_default: boolean
  system_prompt: string
  provider_id: number | null
  model: string | null
  mode: 'human_in_loop' | 'react'
  max_iterations: number
  created_at: string
  updated_at: string
  deleted_at: string | null
  skill_ids: number[]
}

export type AgentConfigWrite = Omit<AgentConfig, 'id' | 'is_default' | 'created_at' | 'updated_at' | 'deleted_at' | 'skill_ids'>

export interface AgentApiKey {
  id: number
  agent_id: number
  label: string
  key_prefix: string
  enabled: boolean
  expires_at: string | null
  last_used_at: string | null
  created_at: string
  updated_at: string
  revoked_at: string | null
}

export interface AgentApiKeyCreated extends AgentApiKey {
  secret: string
}

export interface SkillSummary {
  id: number
  name: string
  description: string | null
  system_prompt: string
  running: boolean
  tools: ToolSummary[]
}

export interface ChatTurnRequest {
  message: string
  conversation_id: string | null
  agent_id?: number
}

export interface ChatTurnResponse {
  status: 'completed' | 'needs_input'
  conversation_id: string
  agent_id: number
  agent_name: string
  message: string
  loaded_skill_ids: number[]
  pending: Record<string, unknown> | null
}
