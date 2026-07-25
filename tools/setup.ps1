<# 
================================================================================
CEREBRO-X v22.1  —  Build & Run Script (PowerShell)
================================================================================
File: setup.ps1

PREREQUISITES:
  1. Docker Desktop installed and running
  2. Git (optional, for version control)
  3. Python 3.10+ (for local testing without Docker)

USAGE:
  .\setup.ps1 -Action build       # Build Docker images
  .\setup.ps1 -Action run         # Start all services
  .\setup.ps1 -Action test        # Run tests locally
  .\setup.ps1 -Action stop        # Stop all services
  .\setup.ps1 -Action logs        # View live logs
  .\setup.ps1 -Action status      # Check service health
  .\setup.ps1 -Action scale       # Scale API to 4 replicas
  .\setup.ps1 -Action full        # Build + Run (one command)
================================================================================
#>

param(
    [ValidateSet("build", "run", "test", "stop", "logs", "status", "scale", "full", "clean")]
    [string]$Action = "full"
)

$ErrorActionPreference = "Stop"
$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# ─────────────────────────────────────────────────────────────────────────────
# Colors
# ─────────────────────────────────────────────────────────────────────────────
function Write-Step($msg)  { Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Write-OK($msg)    { Write-Host "  ✅ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  ⚠️  $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  ❌ $msg" -ForegroundColor Red }

# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ─────────────────────────────────────────────────────────────────────────────
function Test-Prerequisites {
    Write-Step "Checking prerequisites..."

    # Docker
    try {
        $dockerVersion = docker --version 2>&1
        Write-OK "Docker: $dockerVersion"
    } catch {
        Write-Fail "Docker not found. Install Docker Desktop first."
        Write-Host "  → https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }

    # Docker running?
    try {
        docker info 2>&1 | Out-Null
        Write-OK "Docker daemon is running"
    } catch {
        Write-Fail "Docker daemon not running. Start Docker Desktop first."
        exit 1
    }

    # Docker Compose
    try {
        docker compose version 2>&1 | Out-Null
        Write-OK "Docker Compose available"
    } catch {
        Write-Warn "docker compose not found, trying docker-compose..."
    }

    # .env file
    $envFile = Join-Path $PROJECT_DIR ".env"
    if (-not (Test-Path $envFile)) {
        Write-Warn ".env not found — creating from .env.example"
        Copy-Item (Join-Path $PROJECT_DIR ".env.example") $envFile
        Write-OK "Created .env — edit it with your API keys and passwords"
    } else {
        Write-OK ".env exists"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Actions
# ─────────────────────────────────────────────────────────────────────────────

function Invoke-Build {
    Write-Step "Building Docker images..."
    Set-Location $PROJECT_DIR

    # Build API image
    Write-Host "  Building cerebro-api image..."
    docker build -t cerebro-x-api:latest -f Dockerfile .
    Write-OK "API image built"

    # Build Worker image
    Write-Host "  Building cerebro-worker image..."
    docker build -t cerebro-x-worker:latest -f Dockerfile.worker .
    Write-OK "Worker image built"

    Write-Host "`n  Images:" -ForegroundColor Gray
    docker images | Select-String "cerebro"
}

function Invoke-Run {
    Write-Step "Starting CEREBRO-X services..."
    Set-Location $PROJECT_DIR

    # Create results directory
    $resultsDir = Join-Path $PROJECT_DIR "CEREBRO_RESULTS"
    if (-not (Test-Path $resultsDir)) {
        New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
    }

    # Start with production compose
    docker compose -f docker-compose.prod.yml up -d --remove-orphans

    Write-OK "All services starting..."
    Write-Host ""
    Write-Host "  Services:" -ForegroundColor Gray
    Write-Host "  ├── API Gateway     → http://localhost:80"
    Write-Host "  ├── API Docs        → http://localhost:80/docs"
    Write-Host "  ├── Prometheus      → http://localhost:9090  (if monitoring profile)"
    Write-Host "  ├── Grafana         → http://localhost:3000  (if monitoring profile)"
    Write-Host "  ├── Flower (Celery) → http://localhost:5555  (if monitoring profile)"
    Write-Host "  └── PostgreSQL      → localhost:5432"
    Write-Host ""
    Write-Host "  Default admin login:" -ForegroundColor Yellow
    Write-Host "    Username: admin"
    Write-Host "    Password: (from CEREBRO_ADMIN_PASSWORD in .env)"
    Write-Host ""

    # Wait for health
    Write-Host "  Waiting for services to be healthy..." -NoNewline
    $maxWait = 60
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost/healthz" -TimeoutSec 3 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host ""
                Write-OK "API is healthy!"
                return
            }
        } catch {}
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 3
        $waited += 3
    }
    Write-Host ""
    Write-Warn "Services may still be starting. Check: docker compose -f docker-compose.prod.yml logs"
}

function Invoke-Test {
    Write-Step "Running tests..."
    Set-Location $PROJECT_DIR

    # Check if venv exists
    $venvPath = Join-Path $PROJECT_DIR ".venv"
    if (Test-Path $venvPath) {
        & (Join-Path $venvPath "Scripts\Activate.ps1")
    }

    # Install test deps
    Write-Host "  Installing test dependencies..."
    pip install pytest pytest-cov pytest-asyncio httpx --quiet 2>&1 | Out-Null

    # Run unit tests
    Write-Host "  Running unit tests..."
    python -m pytest tests/unit/ -v --tb=short --cov=src --cov-report=term-missing

    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-OK "All unit tests passed!"
    } else {
        Write-Fail "Some tests failed (exit code: $exitCode)"
    }
}

function Invoke-Stop {
    Write-Step "Stopping all services..."
    Set-Location $PROJECT_DIR
    docker compose -f docker-compose.prod.yml down
    Write-OK "All services stopped"
}

function Invoke-Logs {
    Write-Step "Streaming logs (Ctrl+C to stop)..."
    Set-Location $PROJECT_DIR
    docker compose -f docker-compose.prod.yml logs -f --tail=100
}

function Invoke-Status {
    Write-Step "Service status:"
    Set-Location $PROJECT_DIR
    docker compose -f docker-compose.prod.yml ps

    Write-Host "`n  Health check:" -ForegroundColor Gray
    try {
        $health = Invoke-RestMethod -Uri "http://localhost/healthz" -TimeoutSec 5
        Write-OK "API: $($health.status)"
    } catch {
        Write-Warn "API not responding"
    }
}

function Invoke-Scale {
    Write-Step "Scaling API to 4 replicas..."
    Set-Location $PROJECT_DIR
    docker compose -f docker-compose.prod.yml up -d --scale cerebro-api=4
    Write-OK "Scaled to 4 API replicas"
    docker compose -f docker-compose.prod.yml ps | Select-String "cerebro"
}

function Invoke-Clean {
    Write-Step "Cleaning up everything..."
    Set-Location $PROJECT_DIR
    docker compose -f docker-compose.prod.yml down -v --remove-orphans
    docker rmi cerebro-x-api:latest cerebro-x-worker:latest 2>&1 | Out-Null
    Write-OK "Cleaned up containers, volumes, and images"
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  CEREBRO-X v22.1  |  Build & Run v2.0  ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan

Test-Prerequisites

switch ($Action) {
    "build"  { Invoke-Build }
    "run"    { Invoke-Run }
    "test"   { Invoke-Test }
    "stop"   { Invoke-Stop }
    "logs"   { Invoke-Logs }
    "status" { Invoke-Status }
    "scale"  { Invoke-Scale }
    "clean"  { Invoke-Clean }
    "full"   {
        Invoke-Build
        Invoke-Run
    }
}

Write-Host ""
