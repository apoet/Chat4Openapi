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
  role: 'admin' | 'user'
}

export interface ManagedUser {
  id: number
  username: string
  role: 'user'
  locale: Locale
  enabled: boolean
  created_at: string
}

export interface AuthResponse {
  admin: AdminSummary
  csrf_token: string
}

export interface AdminPasswordResetIssued {
  credential_path: string
  expires_at: string
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
  auth_mode: 'none' | 'oauth' | 'tool'
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

export type ToolBatchAction = 'enable' | 'disable' | 'delete'
export type ToolBatchStatus = 'enabled' | 'disabled' | 'deleted'

export interface ToolBatchSucceeded {
  tool_id: number
  action: ToolBatchAction
  status: ToolBatchStatus
}

export interface ToolBatchFailed {
  tool_id: number
  action: ToolBatchAction
  code: string
  params: Record<string, unknown>
}

export interface ToolBatchResponse {
  request_count: number
  succeeded: ToolBatchSucceeded[]
  failed: ToolBatchFailed[]
}

export interface ToolParameterOverrideWrite {
  description: string | null
  example: unknown | null
}

export interface SourceImportResponse {
  source: ApiSourceSummary
  tools: ToolSummary[]
}

export interface AutoAgentifySkill {
  id: number
  name: string
  tool_ids: number[]
  value: string
}

export interface AutoAgentifyAgent {
  id: number
  name: string
  skill_ids: number[]
  mode: 'human_in_loop' | 'react'
  provider_id: number
  value: string
  use_cases: string[]
}

export interface AutoAgentifyResult {
  source: ApiSourceSummary
  imported_tool_count: number
  enabled_tool_count: number
  skills: AutoAgentifySkill[]
  agents: AutoAgentifyAgent[]
}

export interface SourceRefreshResult {
  created: number
  updated: number
  unchanged: number
}

export interface ToolAuthConfig {
  id?: number
  api_source_id?: number
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
  request_parameters: Record<string, unknown>
  request_headers: Record<string, string>
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

export interface ChatAgentSummary {
  id: number
  name: string
  is_default: boolean
  skill_ids?: number[]
}

export interface AppSettings {
  base_url: string | null
}

export interface OAuthConfigSummary {
  api_source_id: number
  enabled: boolean
  client_id: string
  has_client_secret: boolean
  grant_type: OAuthGrantType
  token_endpoint_auth_method: OAuthTokenEndpointAuthMethod
  token_headers: Record<string, string>
  token_params: Record<string, string>
  authorization_url: string | null
  token_url: string
  device_authorization_url: string | null
  redirect_uri: string | null
  scopes: string[]
  recommended_redirect_uri: string | null
  effective_redirect_uri: string | null
}

export type OAuthTokenEndpointAuthMethod =
  | 'auto'
  | 'client_secret_basic'
  | 'client_secret_post'
  | 'none'

export type OAuthGrantType = 'authorization_code' | 'client_credentials'

export interface OAuthConfigWrite {
  enabled: boolean
  client_id: string
  client_secret: string | null
  grant_type: OAuthGrantType
  token_endpoint_auth_method: OAuthTokenEndpointAuthMethod
  token_headers: Record<string, string>
  token_params: Record<string, string>
  authorization_url: string | null
  token_url: string
  device_authorization_url: string | null
  redirect_uri: string | null
  scopes: string[]
}

export interface ChatBootstrapResponse {
  subject_id: string
  agents: ChatAgentSummary[]
}

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

export interface AgentEmbedConfig {
  id: number
  agent_id: number
  name: string
  public_id: string
  enabled: boolean
  allowed_origins: string[]
  position: 'bottom_right' | 'bottom_left'
  created_at: string
  updated_at: string
  deleted_at: string | null
  script: string | null
}

export type AgentEmbedWrite = Pick<
  AgentEmbedConfig,
  'name' | 'enabled' | 'allowed_origins' | 'position'
>

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
  status: 'completed' | 'needs_input' | 'authorization_required'
  conversation_id: string
  agent_id: number
  agent_name: string
  message: string
  loaded_skill_ids: number[]
  pending: Record<string, unknown> | null
}
