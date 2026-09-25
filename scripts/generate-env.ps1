# scripts/generate-env.ps1 не реализован!
# docker compose --env-file env/.env up -d

$envFile = "env/.env"
$template = Get-Content "env/.env.template" -Raw

# Загружаем текущий .env, чтобы получить сырые переменные
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^([A-Z_]+)="?(.*?)"?$') {
        Set-Variable -Name $matches[1] -Value $matches[2] -Scope Global
    }
}

# Определяем маппинг tier → провайдер
$tiers = @{
    NANO     = @{ Model="openai/generative-model"; Key=$QWEN_API_KEY; Base=$QWEN_BASE_URL; Timeout="60" }
    SMALL    = @{ Model="openai/generative-model"; Key=$QWEN_API_KEY; Base=$QWEN_BASE_URL; Timeout="60" }
    MID      = @{ Model="openai/generative-model"; Key=$QWEN_API_KEY; Base=$QWEN_BASE_URL; Timeout="60" }
    FRONTIER = @{ Model="openai/generative-model"; Key=$QWEN_API_KEY; Base=$QWEN_BASE_URL; Timeout="60" }
    DEEP     = @{ Model="openai/generative-model"; Key=$QWEN_API_KEY; Base=$QWEN_BASE_URL; Timeout="120" }
}

# Подставляем в шаблон
foreach ($tier in $tiers.Keys) {
    $t = $tiers[$tier]
    $template = $template -replace "{{TIER_${tier}_MODEL}}", $t.Model
    $template = $template -replace "{{TIER_${tier}_API_KEY}}", "TIER_${tier}_API_KEY=`"$($t.Key)`""
    $template = $template -replace "{{TIER_${tier}_API_BASE}}", "TIER_${tier}_API_BASE=`"$($t.Base)`""
    $template = $template -replace "{{TIER_${tier}_TIMEOUT}}", "TIER_${tier}_TIMEOUT=$($t.Timeout)"
}

$template | Set-Content "env/.env"
Write-Host "✅ env/.env сгенерирован"
