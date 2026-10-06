# scripts/setup-gum-path.ps1 — одноразовая регистрация gum в PATH
$ErrorActionPreference = "Stop"

$gumExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
    -Recurse -Filter "gum.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $gumExe) {
    Write-Host "❌ gum.exe не найден. Установите: winget install charmbracelet.gum" -ForegroundColor Red
    exit 1
}

$gumDir = Split-Path -Parent $gumExe
Write-Host "Найден: $gumExe" -ForegroundColor Cyan

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$gumDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$gumDir", "User")
    Write-Host "✅ $gumDir добавлен в User PATH" -ForegroundColor Green
    Write-Host "   Откройте новый терминал, чтобы изменения вступили в силу." -ForegroundColor Yellow
} else {
    Write-Host "✅ Уже в User PATH" -ForegroundColor Green
}

$env:PATH = "$env:PATH;$gumDir"

& gum --version
