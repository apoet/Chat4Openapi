# ChatAPI 平台设计规范

日期：2026-07-21
状态：已批准

## 1. 目标与范围

ChatAPI 是一个单实例、单管理员的 API Agent 平台。管理员可以导入 OpenAPI/Swagger 接口或手工创建 HTTP Tool，为接口配置加密凭据，将已启用 Tool 编排为声明式 Skill，并通过内置聊天界面、OpenAI 兼容 API 或 Anthropic 兼容 API 调用模型和 Skill。

首版包括：

- 首次访问初始化管理员，后台管理始终需要登录。
- 可选的聊天前端登录开关。
- OpenAI-compatible 与 Anthropic-compatible 大模型供应商配置。
- OpenAPI 2.0/3.x URL、JSON/YAML 文件导入，以及手工 HTTP Tool。
- Tool 的测试、启用、停用、软删除与重新同步。
- API Key、Bearer Token、Basic Auth、用户名密码登录换 Token。
- 声明式 Skill、Tool 白名单、运行限制、启用与停用。
- 内置流式聊天、会话历史、Tool 调用详情和停止生成。
- OpenAI 与 Anthropic 核心对话协议的原生处理，以及外围端点的受控透明代理。
- 英语和简体中文，默认英语。
- SQLite 存储。

首版不包括多用户、多租户、多后端副本写入、任意代码脚本认证、多步骤认证工作流、外部 OpenAPI `$ref` 自动抓取，或对上游不具备能力的外围接口进行本地模拟。

## 2. 总体架构

采用前后端分离的模块化单体。

- 后端：Python、FastAPI、SQLAlchemy 2、Alembic、Pydantic、HTTPX。
- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus。
- 数据库：SQLite，启用 WAL、外键约束和 busy timeout。
- 部署：Vue 构建产物由 FastAPI 托管；提供本地单命令和 Docker 部署。
- 环境：Node.js 使用 nvm；Python 优先提供 conda 环境文件。
- 国际化：前后端使用稳定消息键，内置 `en-US`、`zh-CN`，默认 `en-US`。

后端模块边界：

- `auth`：初始化、管理员登录、Cookie 会话、CSRF、平台 API Key。
- `providers`：供应商、模型、路由与透明代理。
- `credentials`：凭据加密、认证注入和登录 Token 缓存。
- `tools`：OpenAPI 导入、手工 HTTP Tool、Schema 转换与执行。
- `skills`：Skill 配置、Tool 绑定、提示词引用和运行限制。
- `chat`：对话、消息、上下文裁剪、流式输出和 Agent 循环。
- `compat`：OpenAI/Anthropic 请求、响应、事件流与错误转换。
- `audit`：配置变更与 Tool 调用审计。

外部路由分区：

- `/api/admin/*`：后台配置管理。
- `/api/chat/*`：内置聊天前端。
- `/v1/*`：OpenAI 兼容入口及 Anthropic `messages` 兼容入口。
- `/anthropic/v1/*`：Anthropic 别名入口。
- `/health`：健康检查。

Skill 的“启动/停止”是允许或禁止新调用的持久状态，不创建常驻进程。停用时已开始的调用可以完成。Tool 停用后不能进入新的 Agent 调用。

## 3. 身份与权限

首次访问通过 `/api/setup/status` 判断初始化状态。未初始化时，前端只允许进入初始化向导。向导依次完成语言选择、管理员用户名与密码、加密密钥提示、首个 LLM 供应商配置和连接测试。管理员密码使用 Argon2id 哈希。初始化完成后，公开创建管理员的入口永久关闭。

管理端和已登录聊天使用 HttpOnly、SameSite Cookie 会话及 CSRF 防护。兼容 API 使用平台 API Key；Key 只在创建时显示一次，数据库只保存哈希。平台 Key 可限制允许调用的模型、Skill 和代理能力。

后台管理始终要求登录。聊天登录关闭时，匿名访客只能使用显式公开且不需要认证 Tool 的 Skill，不能枚举或使用管理员保存的 Credential Profile。

## 4. 数据模型

核心实体如下：

- `AdminUser`：用户名、密码哈希、语言、状态和最后登录时间。
- `WebSession`：会话摘要、CSRF 信息、过期时间和撤销时间。
- `PlatformApiKey`：名称、Key 哈希、权限范围、状态和最后使用时间。
- `Provider`：协议类型、Base URL、加密 API Key、自定义请求头和状态。
- `ProviderModel`：上游模型名、公开别名、能力声明和状态。
- `ApiSource`：来源类型、Base URL、规范快照、内容哈希、登录配置和网络策略。
- `Tool`：稳定标识、名称、operation 信息、输入 Schema、响应配置和状态。
- `CredentialProfile`：所属 API Source、认证类型、加密值、Token 缓存策略和状态。
- `Skill`：名称、slug、多语言说明、系统提示词、模型、参数、限制、公开性和状态。
- `SkillToolBinding`：Skill 与 Tool 的绑定及稳定引用名。
- `Conversation`、`Message`：会话、消息、协议角色、用量和结构化元数据。
- `ToolInvocation`：请求 ID、Tool、凭据档案 ID、脱敏参数、状态、耗时和结果摘要。
- `AuditLog`：操作者、动作、目标、请求 ID、状态和脱敏差异。

配置实体具有创建和更新时间、启用状态及软删除时间。引用中的 Tool 不能直接删除；必须先解除 Skill 绑定。

## 5. 凭据与认证

Credential Profile 支持无认证、API Key、Bearer Token、Basic Auth 和用户名密码登录换 Token。Profile 必须绑定单个 API Source，不能跨来源使用。原始凭据以应用级认证加密方式写入 SQLite；主密钥来自环境变量。开发环境允许生成受限权限的数据目录密钥文件，生产环境启动时提示改用环境变量。

保存的用户名、密码和长期 Key 默认不由平台设定过期时间，直到管理员更新、删除或上游拒绝。登录 Token 优先读取 `expires_in` 或 JWT `exp`，并提前 60 秒判定过期。上游不提供有效期时默认缓存 30 分钟，管理员可按 Profile 配置 0 至 24 小时；0 表示每次调用前登录。

登录失败或收到 `401/403` 时，运行层清除缓存 Token，重新登录并最多重试一次。日志、错误、审计和模型上下文均不得包含原始凭据、认证头或完整敏感响应。

Skill 请求传递 API Source 到 Credential Profile 的绑定：

```json
{
  "skill_id": "skill-id",
  "credential_bindings": {
    "api-source-id": "credential-profile-id"
  }
}
```

直接调用 Tool 时传递对应 `credential_profile_id`。运行层先验证归属关系，再在 HTTP 请求发出前注入认证信息。LLM 可以看到 Tool 能力，但不能读取凭据内容。

## 6. OpenAPI 导入与 Tool 执行

API Source 接受 OpenAPI 2.0/3.x URL、JSON/YAML 文件和手工 HTTP Tool。导入器解析文档内 `$ref`，但不自动抓取外部 `$ref`。管理员预览 operation 后选择导入范围。

Tool 名称优先使用 `operationId`，缺失时使用 method 与 path 生成。冲突名称必须由管理员解决。path、query、header、cookie 和 body 参数转换为 JSON Schema。需要认证的 Tool 在管理 Schema 中标记认证要求；对外直接调用参数增加 `credential_profile_id`，Skill Agent 则由已验证的请求级凭据绑定自动注入该字段。

导入保存规范快照及内容哈希。重新同步先展示新增、变更和删除差异，不静默覆盖管理员调整。新 Tool 默认停用，测试成功或管理员明确确认后方可启用。

统一执行器负责：

- Schema 校验与类型转换。
- 将 URL 限制在 API Source 的协议、主机、端口和 Base Path 内。
- 默认拒绝回环、链路本地和私有地址；管理员可显式配置受信任内网目标。
- 限制连接、读取、总超时，请求体、响应体和重定向次数。
- JSON 优先解析；其他响应返回状态码、Content-Type 与截断正文。
- 非 2xx 响应转换为结构化 Tool 错误。
- 使用指定 Profile 在后台进行测试。

手工 HTTP Tool 与 OpenAPI Tool 使用相同的 Schema、认证和执行器。

## 7. Skill 与 Agent 运行

Skill 包含名称、多语言说明、系统提示词、默认供应商和模型、Tool 白名单、温度、最大输出 Token、最大 Agent 循环次数、单 Tool 超时、整轮超时、并行 Tool 开关、公开性和状态。

Agent 每轮加载已启用 Skill 和 Tool，将消息及 Tool Schema 发给供应商，执行模型选择的 Tool，把结构化结果回传模型，并重复至产生最终答复或达到限制。循环、时间或 Token 超限时返回明确终止原因。对话数据库保留完整历史；发送模型前按上下文预算裁剪。

Skill 编辑器右侧提供 Tool Library，按 API Source 分组，只显示已导入且已启用 Tool。支持按名称、说明、HTTP 路径和 Source 搜索并批量绑定。系统提示词输入 `@` 时，只检索当前已绑定 Tool，并插入稳定 Tool 引用；点击引用可查看说明、参数 Schema 和认证要求。

已绑定 Tool 后续停用时保留绑定但显示告警，并阻止 Skill 重新启用。删除 Tool 前必须解除绑定。保存 Skill 时校验提示词 `@tool` 引用与绑定列表一致。

## 8. 内置聊天前端

聊天支持新建、重命名、删除对话，Markdown、代码块、流式输出、停止生成和折叠的 Tool 调用卡片。卡片仅显示 Tool 名称、脱敏参数、耗时和结果摘要。

Skill 选择器位于消息输入框下方，并提供 `No Skill / Direct model`。选择 Skill 后，界面根据其 Tool 来源在同一区域生成 Credential Profile 选择器。凭据齐全时显示就绪状态；缺失时禁用发送并指出缺失来源。切换 Skill 可保留仍适用的绑定，并提示清理不再需要的绑定。

英语和简体中文可即时切换，默认英语。浏览器保存当前选择，已登录管理员的偏好同时持久化。后端返回错误码和消息参数，由前端本地化。

## 9. OpenAI 与 Anthropic 兼容 API

平台通过虚拟模型名路由：

- `openai-compatible/<model>`：OpenAI-compatible 供应商模型。
- `anthropic-compatible/<model>`：Anthropic-compatible 供应商模型。
- `skill/<slug>`：平台 Skill Agent。

凭据绑定通过 `X-ChatAPI-Credential-Bindings` 请求头携带 JSON 映射，也可携带后台创建的绑定配置短 ID。平台 API Key 验证调用权限。

平台原生处理：

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/messages`
- `POST /anthropic/v1/messages`
- `GET /v1/models`

核心接口支持流式和非流式。Skill 的内部 Tool 由平台执行；客户端声明的 Tool 与内部 Tool 分开命名并检查冲突，需由客户端执行的 Tool Call 按目标协议返回。

文件、批处理、图片、音频、嵌入等外围端点，根据明确配置的供应商和路由规则透明代理。只允许后台启用的路径和 HTTP 方法。平台替换上游鉴权，保留供应商支持的字段、状态码、正文和事件流。上游不支持时返回对应兼容错误，不伪造能力。

## 10. 错误、审计与运维

错误分为配置、认证、Tool、Agent 和代理五类。每个请求生成 `request_id`，贯穿兼容网关、Agent、Tool Invocation 和审计。前端展示本地化错误，并允许管理员复制请求 ID。

Alembic 管理数据库版本。启动时检测版本，不执行不可逆静默迁移。后台支持配置和数据库备份；默认导出排除凭据。包含凭据的备份要求重新输入管理员密码，并以独立密码加密。

结构化日志默认输出控制台，不记录提示词全文、密钥、认证头或敏感 Tool 响应。Credential Profile 和平台 API Key 的撤销立即生效。

## 11. 测试与验收

测试层次：

- 单元测试：OpenAPI 转换、认证注入、Token 过期、加密、脱敏和协议转换。
- 集成测试：SQLite 迁移、模拟 LLM、Swagger 登录、Tool 执行和多轮 Agent。
- 契约测试：OpenAI Chat/Responses 与 Anthropic Messages 的流式和非流式格式。
- 前端测试：初始化、登录开关、Tool 导入、Skill `@` 引用、输入框下方选择 Skill 和凭据。
- 端到端测试：初始化、配置供应商、导入 Swagger、创建凭据、启用 Tool、编排 Skill和完成聊天。
- 安全测试：SSRF、恶意 `$ref`、路径覆盖、凭据泄漏、日志脱敏、权限绕过和超大响应。

验收要求：管理员可以从空数据库完成完整端到端流程；OpenAI 与 Anthropic SDK 可以调用普通虚拟模型或 Skill 虚拟模型；流式响应、凭据过期重登、Tool 停用和 Skill 停用行为符合本规范。外围接口兼容性以已配置上游的实际能力为边界。
