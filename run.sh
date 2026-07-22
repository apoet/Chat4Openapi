#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-chat4openapi}"
NODE_VERSION="${NODE_VERSION:-20.19.4}"
BACKEND_PID=""
FRONTEND_PID=""

usage() {
  cat <<'EOF'
Usage: ./run.sh

Starts the Agent4API development backend and frontend.

Optional environment variables:
  CONDA_ENV_NAME  Conda environment name (default: chat4openapi)
  NODE_VERSION    nvm Node.js version (default: 20.19.4)

The script loads .env when present, applies Alembic migrations, and then starts:
  Backend:  http://127.0.0.1:8000
  Frontend: http://127.0.0.1:5173
EOF
}

cleanup() {
  trap - EXIT INT TERM
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

cd "$ROOT_DIR"

if [[ -f .env ]]; then
  while IFS='=' read -r key value || [[ -n "$key" ]]; do
    key="${key#${key%%[![:space:]]*}}"
    key="${key%${key##*[![:space:]]}}"
    [[ -z "$key" || "$key" == \#* ]] && continue
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "Error: invalid variable name in .env: $key" >&2
      exit 1
    fi
    value="${value%$'\r'}"
    if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < .env
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda was not found in PATH." >&2
  exit 1
fi

if ! command -v nvm >/dev/null 2>&1; then
  NVM_SCRIPT="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  if [[ ! -s "$NVM_SCRIPT" ]]; then
    echo "Error: nvm was not found. Install nvm and Node.js $NODE_VERSION." >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$NVM_SCRIPT"
fi
nvm use "$NODE_VERSION"

if ! conda run -n "$CONDA_ENV_NAME" python --version >/dev/null 2>&1; then
  echo "Error: Conda environment '$CONDA_ENV_NAME' is unavailable." >&2
  echo "Create it with: conda env create --solver libmamba -f environment.yml" >&2
  exit 1
fi
if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  echo "Error: frontend dependencies are missing." >&2
  echo "Run: (cd frontend && npm install)" >&2
  exit 1
fi

echo "Applying database migrations..."
conda run --no-capture-output -n "$CONDA_ENV_NAME" \
  alembic -c backend/alembic.ini upgrade head

trap cleanup EXIT INT TERM

echo "Starting backend at http://127.0.0.1:8000"
conda run --no-capture-output -n "$CONDA_ENV_NAME" \
  uvicorn chat4openapi.main:app --app-dir backend/src \
  --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Starting frontend at http://127.0.0.1:5173"
(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
) &
FRONTEND_PID=$!

echo "Press Ctrl+C to stop both processes."
set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
STATUS=$?
set -e
exit "$STATUS"
