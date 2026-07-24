<p align="center">
  <img src="logo.png" alt="Agent4API Logo" width="180">
</p>

<h1 align="center">Agent4API</h1>

<p align="center">
  <a href="README.md">English</a> | 简体中文
</p>

<p align="center">
  <strong>快速将 OpenAPI 接口重新编排成 Agent</strong>
</p>

> **DEMO 地址：**[https://agent4api.ecrfs.com/admin](https://agent4api.ecrfs.com/admin)<br>
> **用户名：**`demo`<br>
> **密码：**`demo123`

## 项目简介

Agent4API 诞生的目的，是帮助你快速将 OpenAPI 接口重新编排成 Agent，并且无缝集成独立 Chat 和 Embed Chat。

我们支持**一键导入** Swagger 2.0 或 OpenAPI 3.x 文档。Agent4API 会理解接口所承载的业务能力，自动完成 Tools、Skills 和 Agents 的生成与编排。你不需要逐个整理接口、编写 Skill 或配置 Agent，导入后即可开始对话，也可以通过 MCP、OpenAI 兼容接口和 Anthropic 兼容接口接入已有应用。

Agent4API 采用清晰的 **1 个输入、3 类服务** 模型：

- **1 个输入——Swagger/OpenAPI：**支持通过 URL 或 JSON/YAML 文件导入，也可对已有 API 来源再次一键生成。
- **3 类服务：**
  1. **Tools MCP：**通过模型上下文协议（MCP）对外提供已导入的 Tools。
  2. **Agent API：**通过 OpenAI 兼容和 Anthropic 兼容 API 对外提供配置完成的 Agent。
  3. **Chat 和 Embed Chat：**在内置浏览器 Chat 中使用 Agent，或将固定 Agent 嵌入现有网站。

项目采用 FastAPI、Vue 和 SQLite 构建，管理界面支持英文与简体中文。完整文档请参阅 [GitHub Wiki](https://github.com/apoet/Agent4API/wiki)。

<p align="center">
  <img src="docs/images/workflow.zh-CN.svg" alt="Swagger 和 OpenAPI 文档导入为 Tools，Skills 引用 Tools，Agent 绑定 Skills，Chat 与 Agent 发起会话" width="100%">
</p>

![Agent4API 管理后台与对话演示](docs/images/agent4api-workflow.gif)

## 核心能力：一键生成 API Agent

配置并启用 LLM 供应商后，进入 **API 来源** 页面：

1. 填写来源名称，并提供 Swagger/OpenAPI URL 或 JSON/YAML 文件；
2. 点击 **一键生成**，选择负责分析的 LLM 供应商；
3. 选择允许识别的系统能力，也可添加需要优先分析的自定义业务能力；
4. 启动生成并实时查看分析过程与最终成果。

对于已经导入的 API 来源，可直接点击来源卡片上的 **一键生成**，无需重新上传文档。

一次生成会自动完成整条编排链路：

- 解析接口并创建受控 Tools；
- 从整体或分业务域理解接口关系，识别、归并并去重真实业务能力；
- 最多生成 20 个聚焦业务能力的 Skills 和 10 个核心 Agents；
- 只启用 Skills 实际引用的 Tools，并立即启动生成的 Skills；
- 启用生成的 Agents，绑定所选供应商及其默认模型；
- 对包含写入或高影响操作的工作流采用 human-in-loop 模式；
- 展示已发现接口数、业务能力、核心流程、业务价值、Skill/Agent 数量及生成进度；
- 检测请求体 Schema 缺失、字段类型或说明不完整等问题，提示改进 OpenAPI 文档。

生成数量是上限而不是目标。系统会优先产出少而完整、最能体现 API 核心价值的组合，
而不是机械地为每个接口创建一个 Skill。模型结果会经过结构校验和引用检查，无效时
自动纠正或使用安全回退方案。

生成任务在后台运行：关闭向导不会中止任务，再次打开可恢复进度；运行中也可主动停止。
来源、Tools、Skills 和 Agents 采用原子化保存，失败时不会留下半成品配置，可调整能力
范围后安全重试。

## 快速开始

### 使用 Docker

已发布的中央仓库镜像为 `apoet2003/agent4api:latest`。如需修改 Docker Hub 用户名、镜像标签或访问端口，先复制 `.env.example` 为 `.env` 并修改对应配置。

从 Docker Hub 拉取已发布镜像并启动，无需本地构建：

```shell
docker compose pull
docker compose up -d
```


容器仅开放一个端口，前端页面、API、MCP 和嵌入资源均通过同一地址及相对路径访问。默认管理页面为 [http://127.0.0.1:8000](http://127.0.0.1:8000)。SQLite 数据及加密密钥保存在 `agent4api-data` 数据卷中。

### 从源码运行

#### 1. 安装运行环境

- Python `3.12`
- Node.js `20.19.4`，使用 nvm 或 nvm-windows 管理
- 可选：支持 `libmamba` 求解器的 Conda

任选一种方式创建 Python 环境。

在 Windows 命令提示符中使用 `venv` 和 pip：

```cmd
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

在 Linux 或 macOS shell 中使用 `venv` 和 pip：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

使用 Conda：

```shell
conda env create --solver libmamba -f environment.yml
conda activate agent4api
```

#### 2. 安装前端依赖并创建配置

```shell
nvm use 20.19.4
cd frontend
npm install
cd ..
```

Windows 命令提示符：

```cmd
copy .env.example .env
```

Linux 或 macOS shell：

```bash
cp .env.example .env
```

启动应用前，请检查并按需修改 `.env`。

#### 3. 启动应用

使用 Conda 环境时，可运行快捷启动脚本：

```cmd
run.bat
```

```bash
./run.sh
```

使用手动创建的 Python 环境时，激活环境并启动后端：

```shell
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn chat4openapi.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

然后在另一个终端中启动前端：

```shell
nvm use 20.19.4
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

#### 4. 打开管理页面

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)，首次运行向导会引导你创建管理员账户。

### 管理员密码恢复

在登录页点击“申请重置密码”。Agent4API 会在服务器私有文件
`data/password-reset/admin-password-reset.key` 中生成一个 15 分钟有效的
一次性 Key（Docker 部署时位于 `/app/data` 数据卷内）。请在服务器上读取该
文件，然后在重置页面填写 Key 和新密码。Key 不会通过 API 返回，并会在使用
或过期后删除。可通过 `CHAT4OPENAPI_ADMIN_PASSWORD_RESET_DIR` 和
`CHAT4OPENAPI_ADMIN_PASSWORD_RESET_MINUTES` 配置目录与有效期。
