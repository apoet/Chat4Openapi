# Chat4Openapi 平台设计规范

日期：2026-07-21
状态：已批准

## 1. 目标与范围

Chat4Openapi 是一个单实例、单后台管理员的 API Agent 平台。管理员可以导入 OpenAPI/Swagger 接口或手工创建 HTTP Tool，从已导入 Tool 中指定唯一的全局业务登录接口，将已启用 Tool 编排为声明式 Skill，并通过内置聊天界面、OpenAI 兼容 API 或 Anthropic 兼容 API 调用模型和 Skill。后台管理员与调用原 API 的业务用户属于完全独立的身份域。

首版包括：

- 首次访问初始化唯一后台管理员，后台管理始终需要管理员登录。
- 可选的全局原 API 登录；启用后，聊天用户必须先通过指定 Swagger 登录接口认证。
- OpenAI-compatible 与 Anthropic-compatible 大模型供应商配置。
- OpenAPI 2.0/3.x URL、JSON/YAML 文件导入，以及手工 HTTP Tool。
- Tool 的测试、启用、停用、软删除与重新同步。
- 全局业务登录接口、临时 Tool Session、Token 自动刷新，以及 Bearer、Cookie 或自定义 Header 注入。
- 声明式 Skill、Tool 白名单、运行限制、启用与停用。
- 内置流式聊天、会话历史、Tool 调用详情和停止生成。
- OpenAI 与 Anthropic 核心对话协议的原生处理，以及外围端点的受控透明代理。
- 英语和简体中文，默认英语。
- SQLite 存储。

首版不包括多用户、多租户、多后端副本写入、任意代码脚本认证、多步骤认证工作流、外部 OpenAPI `$ref` 自动抓取，或对上游不具备能力的外围接口进行本地模拟。

## 2. 总体架构

采用前后端分离的模块化单体。

- 后端：Python、FastAPI、SQLAlchemy 2、Alembic、Pydantic、HTTPX。
- MCP：固定使用 `fastmcp==3.4.4` 作为 MCP 协议和 OpenAPI Tool 生成基础；不使用仍处于预发布阶段的 MCP Python SDK v2。
- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus。
- 数据库：SQLite，启用 WAL、外键约束和 busy timeout。
- 部署：Vue 构建产物由 FastAPI 托管；提供本地单命令和 Docker 部署。
- 环境：Node.js 使用 nvm；Python 优先提供 conda 环境文件。
- 国际化：前后端使用稳定消息键，内置 `en-US`、`zh-CN`，默认 `en-US`。

后端模块边界：

- `auth`：初始化、管理员登录、Cookie 会话、CSRF、平台 API Key。
- `providers`：供应商、模型、路由与透明代理。
- `tool_sessions`：全局业务登录、临时 Tool Session、认证注入和 Token 刷新。
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

管理端使用独立的管理员 HttpOnly、SameSite Cookie 会话及 CSRF 防护。聊天端的原 API Tool Session 使用另一个独立 Cookie 名称和作用域。兼容 API 使用平台 API Key；Key 只在创建时显示一次，数据库只保存哈希。平台 Key 可限制允许调用的模型、Skill 和代理能力。

后台管理始终要求管理员登录。启用全局原 API 登录后，聊天访问者必须先通过管理员指定的 Swagger 登录 Tool 认证，所有 Tool 调用使用当前访问者的 Tool Session；管理员身份和管理员密码不能用于 Tool 调用。关闭全局原 API 登录后，聊天和 Tool 调用不要求 Tool Session，也不注入业务用户认证信息。

## 4. 数据模型

核心实体如下：

- `AdminUser`：用户名、密码哈希、语言、状态和最后登录时间。
- `AdminWebSession`：管理员会话摘要、CSRF 信息、过期时间和撤销时间。
- `PlatformApiKey`：名称、Key 哈希、权限范围、状态和最后使用时间。
- `Provider`：协议类型、Base URL、加密 API Key、自定义请求头和状态。
- `ProviderModel`：上游模型名、公开别名、能力声明和状态。
- `ApiSource`：来源类型、Base URL、规范快照、内容哈希和网络策略。
- `Tool`：稳定标识、名称、operation 信息、输入 Schema、响应配置和状态。
- `GlobalToolAuthConfig`：全局登录开关、登录 Tool、请求字段映射、响应提取、认证注入、空闲期限和绝对期限。
- `ToolUserSession`：不透明 ID 哈希、加密临时登录数据、加密认证结果、Token 过期时间、空闲过期时间、绝对过期时间和撤销时间。
- `Skill`：名称、slug、多语言说明、系统提示词、模型、参数、限制、公开性和状态。
- `SkillToolBinding`：Skill 与 Tool 的绑定及稳定引用名。
- `Conversation`、`Message`：会话、消息、协议角色、用量和结构化元数据。
- `ToolInvocation`：请求 ID、Tool、Tool Session ID 摘要、脱敏参数、状态、耗时和结果摘要。
- `AuditLog`：操作者、动作、目标、请求 ID、状态和脱敏差异。

配置实体具有创建和更新时间、启用状态及软删除时间。引用中的 Tool 不能直接删除；必须先解除 Skill 绑定。

## 5. 双身份域与全局 Tool Session

后台管理员与原 API 业务用户完全分离。管理员只能管理配置，不能代表业务用户调用 Tool。业务用户不创建 Chat4Openapi 用户档案，其身份由唯一的全局 Swagger 登录 Tool 验证。

管理员从已导入且启用的 Tool 中指定全局登录 Tool，并配置用户名、密码等请求字段映射，Token、过期时间和其他认证数据的响应提取路径，以及后续 Tool 请求使用的 Bearer、Cookie 或自定义 Header 注入规则。登录 Tool 是唯一允许在没有 Tool Session 时执行的业务接口；绑定后不再出现在 Skill Tool Library，也不能被 LLM 或普通 Tool 调用直接执行。被全局登录配置引用的 Tool 不能停用或删除；必须先关闭登录或更换绑定。登录开关是全局设置，不按 API Source 分别配置。

启用登录后，浏览器访问聊天页必须先提交原 API 用户名和密码。服务端调用全局登录 Tool，成功后创建临时 `ToolUserSession`。浏览器仅获得独立的 HttpOnly、SameSite Cookie；兼容 API 客户端通过登录代理获得只显示一次的不透明 Tool Session ID。服务端只保存 ID 哈希。

同一个 Tool Session 只登录一次，其认证结果用于该会话内的所有 Skills、API Sources 和 Tools。原始登录数据和认证结果使用应用级认证加密临时保存在 SQLite 会话记录中，以便服务重启后在有效期内继续会话并在 Token 过期时重新登录；它们不形成持久业务用户档案。主密钥来自环境变量。开发环境允许生成受限权限的数据目录密钥文件，生产环境启动时提示改用环境变量。

Tool Session 默认空闲有效期为 30 分钟、绝对有效期为 8 小时，管理员可配置。退出、空闲过期、达到绝对期限或管理员清理会话时，服务端删除会话中的加密登录数据和认证结果。登录 Token 优先读取 `expires_in` 或 JWT `exp`，提前 60 秒刷新；上游未提供 Token 有效期时，认证结果默认缓存 30 分钟。

Token 到期时，服务端使用当前会话内的加密临时登录数据自动重新登录。收到 `401/403` 时清除认证结果，重新登录并最多重试一次。登录失败则撤销 Tool Session 并要求用户重新登录。日志、错误、审计和模型上下文均不得包含用户名、密码、Token、认证头或完整敏感响应。

启用登录时，所有 Skill 和 Tool 调用必须携带同一个有效 Tool Session。LLM 只看到 Tool 能力和业务参数，不看到 Tool Session ID 或任何认证数据；执行器在 HTTP 请求发出前自动注入当前会话认证。关闭登录时不要求 Tool Session，也不注入认证。

浏览器使用 `POST /api/tool-session/login`、`GET /api/tool-session/status` 和 `POST /api/tool-session/logout`，Session ID 仅存在于 HttpOnly Cookie。兼容 API 客户端使用 `POST /v1/tool-sessions` 登录，并以 `DELETE /v1/tool-sessions/current` 退出。直接 REST Skill/Tool 调用在顶层请求字段携带 `tool_session_id`，兼容 API 则使用 `X-Chat4Openapi-Tool-Session`；该会话字段是调用级认证参数，不进入 LLM Tool Schema。

## 6. OpenAPI 导入与 Tool 执行

API Source 接受 OpenAPI 2.0/3.x URL、JSON/YAML 文件和手工 HTTP Tool。导入器解析文档内 `$ref`，但不自动抓取外部 `$ref`。管理员预览 operation 后选择导入范围。

导入前使用 `openapi-spec-validator` 检测并验证规范版本。OpenAPI 2.0 先转换为平台内部统一模型，再交给 FastMCP OpenAPI Provider；必须使用 2.0、3.0 和 3.1 固定测试样例验证兼容性。FastMCP 只负责生成候选 MCP Tool 定义和协议对象，SQLite 生命周期、同步差异、全局 Tool Session、动态认证注入、SSRF 防护和审计仍由 Chat4Openapi 自己实现。不得把带固定认证头的共享 `httpx.AsyncClient` 用于业务 Tool 调用。

Tool 名称优先使用 `operationId`，缺失时使用 method 与 path 生成。冲突名称必须由管理员解决。path、query、header、cookie 和 body 参数转换为 JSON Schema。Tool Schema 只包含业务参数，不增加用户名、密码、Token 或 Session ID；认证由当前全局 Tool Session 在执行层统一注入。

导入保存规范快照及内容哈希。重新同步先展示新增、变更和删除差异，不静默覆盖管理员调整。新 Tool 默认停用，测试成功或管理员明确确认后方可启用。

统一执行器负责：

- Schema 校验与类型转换。
- 将 URL 限制在 API Source 的协议、主机、端口和 Base Path 内。
- 默认拒绝回环、链路本地和私有地址；管理员可显式配置受信任内网目标。
- 限制连接、读取、总超时，请求体、响应体和重定向次数。
- JSON 优先解析；其他响应返回状态码、Content-Type 与截断正文。
- 非 2xx 响应转换为结构化 Tool 错误。
- 后台测试要求管理员临时输入原 API 用户凭据，由测试流程创建短期 Tool Session；不使用管理员凭据，也不保存业务用户档案。

手工 HTTP Tool 与 OpenAPI Tool 使用相同的 Schema、认证和执行器。

## 7. Skill 与 Agent 运行

Skill 包含名称、多语言说明、系统提示词、默认供应商和模型、Tool 白名单、温度、最大输出 Token、最大 Agent 循环次数、单 Tool 超时、整轮超时、并行 Tool 开关、公开性和状态。

Agent 每轮加载已启用 Skill 和 Tool，将消息及 Tool Schema 发给供应商，执行模型选择的 Tool，把结构化结果回传模型，并重复至产生最终答复或达到限制。循环、时间或 Token 超限时返回明确终止原因。对话数据库保留完整历史；发送模型前按上下文预算裁剪。

Skill 编辑器右侧提供 Tool Library，按 API Source 分组，只显示已导入且已启用 Tool。支持按名称、说明、HTTP 路径和 Source 搜索并批量绑定。系统提示词输入 `@` 时，只检索当前已绑定 Tool，并插入稳定 Tool 引用；点击引用可查看说明、参数 Schema 和认证要求。

已绑定 Tool 后续停用时保留绑定但显示告警，并阻止 Skill 重新启用。删除 Tool 前必须解除绑定。保存 Skill 时校验提示词 `@tool` 引用与绑定列表一致。

## 8. 内置聊天前端

聊天支持新建、重命名、删除对话，Markdown、代码块、流式输出、停止生成和折叠的 Tool 调用卡片。卡片仅显示 Tool 名称、脱敏参数、耗时和结果摘要。

Skill 选择器位于消息输入框下方，并提供 `No Skill / Direct model`。登录状态位于同一区域：全局原 API 登录启用时显示当前 Tool Session 状态，失效后禁用发送并引导重新登录；不再按 Skill 或 API Source 选择凭据。同一会话切换 Skill 时继续使用同一个 Tool Session。

英语和简体中文可即时切换，默认英语。浏览器保存当前选择；后台管理员的偏好单独持久化，业务 Tool Session 不建立用户偏好档案。后端返回错误码和消息参数，由前端本地化。

## 9. OpenAI 与 Anthropic 兼容 API

平台通过虚拟模型名路由：

- `openai-compatible/<model>`：OpenAI-compatible 供应商模型。
- `anthropic-compatible/<model>`：Anthropic-compatible 供应商模型。
- `skill/<slug>`：平台 Skill Agent。

兼容 API 使用两层身份：平台 API Key 验证调用方使用 Chat4Openapi 的权限，`X-Chat4Openapi-Tool-Session` 携带原 API 业务用户的不透明临时会话 ID。登录启用时，客户端先调用受平台 API Key 保护的 Tool Session 登录代理，再使用同一个 Session ID 调用所有模型、Skill 和 Tool；两层身份不能互相替代。

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

Alembic 管理数据库版本。启动时检测版本，不执行不可逆静默迁移。后台支持配置和数据库备份；备份始终排除 Tool User Session 及其中的临时业务凭据，恢复后所有业务用户必须重新登录。

结构化日志默认输出控制台，不记录提示词全文、业务用户名、密码、Token、密钥、认证头或敏感 Tool 响应。Tool Session 和平台 API Key 的撤销立即生效。

## 11. 测试与验收

测试层次：

- 单元测试：OpenAPI 转换、认证注入、Token 过期、加密、脱敏和协议转换。
- 集成测试：SQLite 迁移、模拟 LLM、全局 Swagger 登录、Tool Session、Token 重登、Tool 执行和多轮 Agent。
- 契约测试：OpenAI Chat/Responses 与 Anthropic Messages 的流式和非流式格式。
- 前端测试：管理员初始化、全局业务登录开关、Tool 导入、Skill `@` 引用、输入框下方选择 Skill 和 Tool Session 失效处理。
- 端到端测试：初始化管理员、配置供应商、导入 Swagger、指定全局登录 Tool、业务用户登录、启用 Tool、编排 Skill 和完成聊天。
- 安全测试：SSRF、恶意 `$ref`、路径覆盖、凭据泄漏、日志脱敏、权限绕过和超大响应。

验收要求：管理员可以从空数据库完成管理配置；两个不同的原 API 用户可分别创建隔离的 Tool Session，并在各自会话中调用同一 Skill 而不串用身份；OpenAI 与 Anthropic SDK 可以携带 Tool Session 调用普通虚拟模型或 Skill 虚拟模型；流式响应、Token 过期重登、会话退出、Tool 停用和 Skill 停用行为符合本规范。外围接口兼容性以已配置上游的实际能力为边界。
