#Requires -Version 5.1
<#
.SYNOPSIS
  Collect production-audit evidence: pytest (revision + kill-switch) + SLA gates.

.DESCRIPTION
  Run from repo root when agent Shell hooks block poetry/pytest.
  Writes a timestamped log under logs/audit-evidence/ (gitignored if logs/ is ignored).

.EXAMPLE
  powershell -File scripts/collect_production_audit_evidence.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$OutDir = Join-Path $RepoRoot "logs\audit-evidence"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $OutDir "evidence-$Stamp.txt"

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o)  $Message"
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "=== production-audit evidence ==="
Write-Log "repo=$RepoRoot"

Write-Log "--- pytest: critic revision + graph order + kill-switch ---"
poetry run pytest `
  tests/unit/test_critic_revision_edge.py `
  tests/unit/test_graph_order.py `
  tests/unit/test_adversarial_drills.py::test_drill_kill_switch_blocks_turns `
  tests/unit/test_tool_policy_week1.py::test_kill_switch_blocks_turns `
  -q --tb=line 2>&1 | Tee-Object -FilePath $Log -Append
Write-Log "pytest_exit=$LASTEXITCODE"

Write-Log "--- SLA math gate ---"
poetry run python scripts/run_sla_gates.py --check-math 2>&1 | Tee-Object -FilePath $Log -Append
Write-Log "sla_math_exit=$LASTEXITCODE"

$healthOk = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 5
    Write-Log "health_status=$($resp.StatusCode)"
    $healthOk = ($resp.StatusCode -eq 200)
} catch {
    Write-Log "health_unavailable=$($_.Exception.Message)"
}

if ($healthOk) {
    Write-Log "--- load-health concurrency=50 ---"
    poetry run python scripts/run_sla_gates.py --load-health --concurrency 50 --max-p95-ms 3000 --base-url http://127.0.0.1:8000 2>&1 |
        Tee-Object -FilePath $Log -Append
    Write-Log "load50_exit=$LASTEXITCODE"

    Write-Log "--- load-health concurrency=1000 (staging-style) ---"
    poetry run python scripts/run_sla_gates.py --load-health --concurrency 1000 --max-p95-ms 3000 --base-url http://127.0.0.1:8000 2>&1 |
        Tee-Object -FilePath $Log -Append
    Write-Log "load1000_exit=$LASTEXITCODE"
} else {
    Write-Log "SKIP load-health: API not up on :8000 (start compose/uvicorn first)"
}

Write-Log "=== done; log=$Log ==="
Write-Host ""
Write-Host "Paste this log path back to the agent to update the canvas verdicts:" -ForegroundColor Cyan
Write-Host $Log
