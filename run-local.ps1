<#
.SYNOPSIS
    Run the full GateSense stack locally for testing:
    Postgres (Docker) -> migrations -> optional seed -> backend + frontend dev servers.

.DESCRIPTION
    Orchestrates everything needed to exercise the app end-to-end on one machine.
    The backend and frontend each launch in their own terminal window so you can
    read their logs and Ctrl+C them independently. Postgres keeps running in Docker.

    DATABASE_URL is set explicitly (localhost:55432) so it always wins over the
    checked-in .env, whatever that happens to contain.

.PARAMETER Seed
    Reseed the database (3 societies x 60 residents + demo logins) after migrating.

.PARAMETER Fresh
    Wipe the Postgres volume first (docker-compose down -v). Implies a reseed.

.PARAMETER InstallDeps
    Create/populate the Python venv and run `npm install` if either is missing.

.PARAMETER NoBackend
    Skip launching the backend dev server.

.PARAMETER NoFrontend
    Skip launching the frontend dev server.

.EXAMPLE
    .\run-local.ps1                 # bring everything up (migrates, no reseed)
    .\run-local.ps1 -Seed           # + reseed demo data
    .\run-local.ps1 -Fresh          # wipe DB, migrate, reseed, run
    .\run-local.ps1 -InstallDeps    # first-time setup (venv + npm install) then run
#>
[CmdletBinding()]
param(
    [switch]$Seed,
    [switch]$Fresh,
    [switch]$InstallDeps,
    [switch]$NoBackend,
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
$Root         = $PSScriptRoot
$DbUrl        = 'postgresql://gatesense:gatesense@localhost:55432/gatesense'
$BackendPort  = 8000
$FrontendPort = 5173
$VenvPython   = Join-Path $Root '.venv\Scripts\python.exe'
$FrontendDir  = Join-Path $Root 'frontend'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Set-Location $Root

# ---------------------------------------------------------------------------
# 1. Docker must be running
# ---------------------------------------------------------------------------
Write-Step 'Checking Docker'
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw }
    Write-Ok 'Docker is running.'
} catch {
    Write-Error 'Docker does not appear to be running. Start Docker Desktop and retry.'
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Postgres (optionally wiped)
# ---------------------------------------------------------------------------
if ($Fresh) {
    Write-Step 'Wiping Postgres volume (--Fresh)'
    docker-compose down -v
    $Seed = $true   # a fresh volume has no data, so always reseed
}

Write-Step 'Starting Postgres (docker-compose up -d db)'
docker-compose up -d db
if ($LASTEXITCODE -ne 0) { Write-Error 'Failed to start the Postgres container.'; exit 1 }

Write-Step 'Waiting for Postgres to accept connections'
$dbContainer = (docker-compose ps -q db).Trim()
$ready = $false
foreach ($i in 1..30) {
    docker exec $dbContainer pg_isready -U gatesense *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { Write-Error 'Postgres did not become ready within 30s.'; exit 1 }
Write-Ok 'Postgres is ready on localhost:55432.'

# ---------------------------------------------------------------------------
# 3. Python venv + deps
# ---------------------------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    if ($InstallDeps) {
        Write-Step 'Creating Python venv (.venv) and installing requirements'
        python -m venv (Join-Path $Root '.venv')
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r (Join-Path $Root 'requirements.txt')
    } else {
        Write-Error "No venv at $VenvPython. Run once with -InstallDeps to create it."
        exit 1
    }
}

# Set for THIS process; child dev-server windows inherit it (python-dotenv won't
# override an already-set env var, so this beats the checked-in .env).
$env:DATABASE_URL = $DbUrl

# ---------------------------------------------------------------------------
# 4. Migrations (+ optional seed)
# ---------------------------------------------------------------------------
Write-Step 'Applying database migrations (alembic upgrade head)'
& $VenvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Error 'Migration failed.'; exit 1 }
Write-Ok 'Schema is up to date.'

if ($Seed) {
    Write-Step 'Seeding demo data (backend.seed)'
    & $VenvPython -m backend.seed
    if ($LASTEXITCODE -ne 0) { Write-Error 'Seed failed.'; exit 1 }
}

# ---------------------------------------------------------------------------
# 5. Backend dev server (own window)
# ---------------------------------------------------------------------------
if (-not $NoBackend) {
    Write-Step "Launching backend  -> http://localhost:$BackendPort"
    $backendCmd = @"
Set-Location '$Root'
`$env:DATABASE_URL = '$DbUrl'
Write-Host 'GateSense backend (uvicorn --reload)' -ForegroundColor Cyan
& '$VenvPython' -m uvicorn backend.main:app --reload --port $BackendPort
"@
    Start-Process powershell -ArgumentList '-NoExit', '-Command', $backendCmd | Out-Null
    Write-Ok 'Backend starting in a new window.'
}

# ---------------------------------------------------------------------------
# 6. Frontend dev server (own window)
# ---------------------------------------------------------------------------
if (-not $NoFrontend) {
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        if ($InstallDeps) {
            Write-Step 'Installing frontend dependencies (npm install)'
            Push-Location $FrontendDir
            npm install
            Pop-Location
        } else {
            Write-Warn 'frontend/node_modules missing - run with -InstallDeps (or `npm install` in frontend/). Skipping frontend.'
            $NoFrontend = $true
        }
    }
}
if (-not $NoFrontend) {
    Write-Step "Launching frontend -> http://localhost:$FrontendPort"
    $frontendCmd = @"
Set-Location '$FrontendDir'
Write-Host 'GateSense frontend (vite)' -ForegroundColor Cyan
npm run dev
"@
    Start-Process powershell -ArgumentList '-NoExit', '-Command', $frontendCmd | Out-Null
    Write-Ok 'Frontend starting in a new window.'
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host "`n--------------------------------------------" -ForegroundColor DarkGray
Write-Host " GateSense is starting up" -ForegroundColor White
Write-Host "   Frontend : http://localhost:$FrontendPort"
Write-Host "   Backend  : http://localhost:$BackendPort  (docs: /docs)"
Write-Host "   Postgres : localhost:55432  (db: gatesense)"
Write-Host ""
Write-Host " Demo logins (password: password123):" -ForegroundColor White
Write-Host "   platform_admin : platform@gatesense.in"
Write-Host "   society_admin  : admin@green.gatesense.in"
Write-Host "   guard          : guard1@green.gatesense.in"
Write-Host "   resident       : resident@green.gatesense.in"
Write-Host ""
Write-Host " Backend & frontend run in their own windows - close them or Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host " Postgres stays up; run 'docker-compose down' to stop it." -ForegroundColor DarkGray
Write-Host "--------------------------------------------" -ForegroundColor DarkGray
