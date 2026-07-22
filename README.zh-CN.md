<p align="center">
  <img src="logo.png" alt="Chat4Openapi Logo" width="180">
</p>

<h1 align="center">Chat4Openapi</h1>

<p align="center">
  <a href="README.md">English</a> | 简体中文
</p>

## 项目简介

Chat4Openapi 可将 Swagger/OpenAPI 接口转换为统一管理的工具（Tool），并让独立配置的智能体（Agent）按顺序加载技能（Skill）目录，通过浏览器、OpenAI 兼容接口或 Anthropic 兼容接口提供服务。

项目采用 FastAPI、Vue 和 SQLite 构建，管理界面支持英文与简体中文。架构、功能、兼容接口、身份认证、运维和安全等详细说明请参阅 [GitHub Wiki](https://github.com/apoet/Chat4Openapi/wiki)。

## 快速开始

### 1. 安装运行环境

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
conda activate chat4openapi
```

### 2. 安装前端依赖并创建配置

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

### 3. 启动应用

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

### 4. 打开管理页面

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)，首次运行向导会引导你创建管理员账户。
