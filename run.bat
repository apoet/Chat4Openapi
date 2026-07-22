@echo off
setlocal EnableExtensions DisableDelayedExpansion

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if not "%~1"=="" (
  echo Unknown argument: %~1 1>&2
  goto :help_error
)

set "ROOT_DIR=%~dp0"
if not defined CONDA_ENV_NAME set "CONDA_ENV_NAME=chat4openapi"
if not defined NODE_VERSION set "NODE_VERSION=20.19.4"
pushd "%ROOT_DIR%" || exit /b 1

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

where conda >nul 2>nul || (
  echo Error: conda was not found in PATH. 1>&2
  goto :failed
)
where nvm >nul 2>nul || (
  echo Error: nvm-windows was not found in PATH. 1>&2
  goto :failed
)

call nvm use %NODE_VERSION% || goto :failed
where npm >nul 2>nul || (
  echo Error: npm was not found after selecting Node.js %NODE_VERSION%. 1>&2
  goto :failed
)
call conda run -n "%CONDA_ENV_NAME%" python --version >nul 2>nul || (
  echo Error: Conda environment "%CONDA_ENV_NAME%" is unavailable. 1>&2
  echo Create it with: conda env create --solver libmamba -f environment.yml 1>&2
  goto :failed
)
if not exist "frontend\node_modules\.bin\vite.cmd" (
  echo Error: frontend dependencies are missing. 1>&2
  echo Run: cd frontend ^&^& npm install 1>&2
  goto :failed
)

echo Applying database migrations...
call conda run --no-capture-output -n "%CONDA_ENV_NAME%" alembic -c backend/alembic.ini upgrade head || goto :failed

echo Starting backend at http://127.0.0.1:8000
start "Chat4Openapi Backend" /D "%ROOT_DIR%" cmd /k "conda run --no-capture-output -n %CONDA_ENV_NAME% uvicorn chat4openapi.main:app --app-dir backend/src --host 127.0.0.1 --port 8000"

echo Starting frontend at http://127.0.0.1:5173
start "Chat4Openapi Frontend" /D "%ROOT_DIR%frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"

echo.
echo Chat4Openapi is starting in two terminal windows.
echo Close both windows to stop the development servers.
popd
exit /b 0

:help
echo Usage: run.bat
echo.
echo Starts the Chat4Openapi development backend and frontend.
echo Loads .env when present, applies Alembic migrations, and opens:
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: http://127.0.0.1:5173
echo.
echo Optional environment variables set before running:
echo   CONDA_ENV_NAME  Conda environment name ^(default: chat4openapi^)
echo   NODE_VERSION    nvm Node.js version ^(default: 20.19.4^)
exit /b 0

:help_error
call :help
exit /b 2

:failed
popd
exit /b 1
