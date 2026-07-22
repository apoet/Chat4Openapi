<p align="center">
  <img src="logo.png" alt="Chat4Openapi logo" width="180">
</p>

<h1 align="center">Chat4Openapi</h1>

<p align="center">
  English | <a href="README.zh-CN.md">简体中文</a>
</p>

## Introduction

Chat4Openapi turns Swagger/OpenAPI operations into managed Tools and lets independently configured Agents load ordered Skill catalogs to answer browser, OpenAI-compatible, and Anthropic-compatible requests.

It is a single FastAPI/Vue application backed by SQLite, with an English and Simplified Chinese administration interface. For architecture, features, compatible APIs, authentication, operations, and security details, see the [GitHub Wiki](https://github.com/apoet/Chat4Openapi/wiki).

## Quick start

### 1. Install the required runtimes

- Python `3.12`
- Node.js `20.19.4`, managed with nvm or nvm-windows
- Optional: Conda with the `libmamba` solver

Choose one of the following Python environment options.

Windows Command Prompt with `venv` and pip:

```cmd
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux or macOS shell with `venv` and pip:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Conda:

```shell
conda env create --solver libmamba -f environment.yml
conda activate chat4openapi
```

### 2. Install the frontend and create the configuration

```shell
nvm use 20.19.4
cd frontend
npm install
cd ..
```

Windows Command Prompt:

```cmd
copy .env.example .env
```

Linux or macOS shell:

```bash
cp .env.example .env
```

Review `.env` before starting the application.

### 3. Start the application

With the Conda environment, use the convenience script:

```cmd
run.bat
```

```bash
./run.sh
```

For a manually created Python environment, activate it and start the backend:

```shell
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn chat4openapi.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

Then start the frontend in a second terminal:

```shell
nvm use 20.19.4
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

### 4. Open the administration page

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first-run wizard will guide you through creating the administrator account.
