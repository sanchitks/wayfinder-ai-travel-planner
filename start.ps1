# Starts the Wayfinder backend (FastAPI :8000) and frontend (Next.js :3000).
# First run installs dependencies. Usage:  powershell -ExecutionPolicy Bypass -File start.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$backend = Join-Path $root "backend"
if (-not (Test-Path (Join-Path $backend ".venv"))) {
    Write-Host "Creating Python environment (needs uv: https://docs.astral.sh/uv/)..."
    Push-Location $backend
    uv venv --python 3.14 .venv
    uv pip install --python .venv -r requirements.txt
    Pop-Location
}

$frontend = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Push-Location $frontend
    npm install
    Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backend'; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev"
Write-Host "Backend:  http://localhost:8000/docs"
Write-Host "Frontend: http://localhost:3000"
