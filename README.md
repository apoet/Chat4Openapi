# ChatAPI

Chat with your APIs through managed MCP Tools and Skills.

The current implementation contains the platform foundation: SQLite migrations, first-run
single-administrator setup, secure administrator sessions, English/Chinese localization, and a
Vue administration shell. OpenAPI Tool import, global business-user Tool Sessions, Skills, chat,
and compatible APIs are implemented in the following phases described under `docs/superpowers`.

## Requirements

- Conda
- nvm-windows
- Node.js 20.19.4

## Backend development

Create the Python 3.12 environment and migrate the database:

```powershell
conda env create --solver libmamba -f environment.yml
conda run -n chatapi alembic -c backend/alembic.ini upgrade head
```

If an existing `chatapi` environment needs refreshing:

```powershell
conda run -n chatapi python -m pip install -e "backend[dev]"
```

Start FastAPI:

```powershell
conda run -n chatapi uvicorn chatapi.main:app --app-dir backend/src --reload
```

Run backend verification:

```powershell
conda run -n chatapi python -m pytest backend/tests -q
conda run -n chatapi ruff check backend
```

## Frontend development

```powershell
nvm use 20.19.4
Set-Location frontend
npm install
npm run dev
```

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

Run frontend verification:

```powershell
npm test
npm run typecheck
npm run build
```

After `npm run build`, FastAPI serves `frontend/dist` and provides SPA fallback for browser routes.
Unknown `/api/*`, `/v1/*`, and `/anthropic/*` paths always remain JSON 404 responses.

## First run

1. Open `http://127.0.0.1:8000` after building the frontend, or use the Vite development URL.
2. Select English or Simplified Chinese.
3. Create the sole backend administrator with a password of at least 12 characters.
4. Sign in to reach the administration overview.

The backend administrator is never used as the identity for imported API Tools. Tool users will
authenticate through the globally configured original-API login Tool in the Tool Runtime phase.
