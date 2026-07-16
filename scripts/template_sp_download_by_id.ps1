# ============================================================
# SCRIPT: Download por UniqueId (download.aspx?UniqueId=...)
# Placeholders: {{SITE_URL}} {{PASTA_DESTINO}} {{NOME_ARQUIVO}} {{UNIQUE_ID}}
# ============================================================

$env:PNPLEGACYMESSAGE = 'false'

if (-not (Get-Module -ListAvailable -Name SharePointPnPPowerShellOnline)) {
    Write-Host "Instalando modulo SharePointPnPPowerShellOnline..." -ForegroundColor Yellow
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    Install-Module SharePointPnPPowerShellOnline -Scope CurrentUser -Force -AllowClobber
    Write-Host "Modulo instalado com sucesso!" -ForegroundColor Green
}

Import-Module SharePointPnPPowerShellOnline -Force -WarningAction SilentlyContinue

if (-not (Get-Command Connect-PnPOnline -ErrorAction SilentlyContinue)) {
    Write-Host "FALHA: Modulo nao carregado. Feche e reabra o PowerShell e tente novamente." -ForegroundColor Red
    exit 1
}

$siteUrl      = "{{SITE_URL}}"
$pastaDestino = "{{PASTA_DESTINO}}"
$nomeArquivo  = "{{NOME_ARQUIVO}}"
$uniqueId     = "{{UNIQUE_ID}}"

Write-Host "Conectando ao SharePoint..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

if (-not (Test-Path -Path $pastaDestino)) {
    New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
    Write-Host "Pasta criada: $pastaDestino" -ForegroundColor Green
}

Write-Host "Localizando arquivo por UniqueId: $uniqueId ..." -ForegroundColor Cyan

try {
    $meta = Invoke-PnPSPRestMethod -Url "_api/web/GetFileById('$uniqueId')?`$select=Name,ServerRelativeUrl"
} catch {
    Write-Host "FALHA ao resolver UniqueId: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Compatibilidade com diferentes formatos de retorno do PnP
$serverRelativeUrl = $null
$nomeRemoto = $null
if ($meta.ServerRelativeUrl) {
    $serverRelativeUrl = $meta.ServerRelativeUrl
    $nomeRemoto = $meta.Name
} elseif ($meta.d -and $meta.d.ServerRelativeUrl) {
    $serverRelativeUrl = $meta.d.ServerRelativeUrl
    $nomeRemoto = $meta.d.Name
}

if (-not $serverRelativeUrl) {
    Write-Host "FALHA: nao foi possivel obter ServerRelativeUrl do UniqueId." -ForegroundColor Red
    exit 1
}

if (-not $nomeArquivo -or $nomeArquivo.Trim() -eq "") {
    $nomeArquivo = $nomeRemoto
}

Write-Host "Arquivo resolvido: $serverRelativeUrl ($nomeArquivo)" -ForegroundColor Green
Write-Host "Baixando $nomeArquivo ..." -ForegroundColor Cyan

Get-PnPFile `
    -Url $serverRelativeUrl `
    -Path $pastaDestino `
    -Filename $nomeArquivo `
    -AsFile `
    -Force

$caminhoCompleto = Join-Path $pastaDestino $nomeArquivo
if (Test-Path $caminhoCompleto) {
    Write-Host "SUCESSO: $caminhoCompleto" -ForegroundColor Green
} else {
    Write-Host "FALHA: Arquivo nao encontrado apos download." -ForegroundColor Red
    exit 1
}
