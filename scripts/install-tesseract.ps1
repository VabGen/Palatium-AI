# scripts/install-tesseract.ps1
# powershell -ExecutionPolicy Bypass -File install-tesseract.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

# 1. Установка Tesseract
choco install tesseract -y

# 2. Подхватить PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
            [System.Environment]::GetEnvironmentVariable("Path","User")

# 3. Проверка бинаря
if (-not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    throw "Tesseract не установлен. Проверь логи Chocolatey."
}

# 4. Русская языковая модель
$tessdata = "C:\Program Files\Tesseract-OCR\tessdata"
$rusPath = Join-Path $tessdata "rus.traineddata"
if (-not (Test-Path $rusPath)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest `
        -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata" `
        -OutFile $rusPath
}

# 5. Финальная проверка
Write-Host "`n=== Tesseract установлен ===" -ForegroundColor Green
& tesseract --version
& tesseract --list-langs
