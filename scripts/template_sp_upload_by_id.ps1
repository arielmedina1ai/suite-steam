# ============================================================
# SCRIPT: Sobrescreve arquivo por UniqueId (catalog.json)
# Placeholders: {{SITE_URL}} {{ARQUIVO_LOCAL}} {{UNIQUE_ID}}
# ============================================================

$env:PNPLEGACYMESSAGE = 'false'
$ErrorActionPreference = "Continue"

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
$arquivoLocal = "{{ARQUIVO_LOCAL}}"
$uniqueIdRaw  = "{{UNIQUE_ID}}"

if (-not (Test-Path -Path $arquivoLocal)) {
    Write-Host "FALHA: Arquivo local nao encontrado: $arquivoLocal" -ForegroundColor Red
    exit 1
}

Write-Host "Conectando ao SharePoint (WebLogin)..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

function ConvertTo-GuidSafe([string]$raw) {
    $t = $raw.Trim().Trim("{}")
    try { return [Guid]::Parse($t) } catch { }
    $hex = ($t -replace "[^0-9a-fA-F]", "")
    if ($hex.Length -eq 32) {
        $withDashes = "{0}-{1}-{2}-{3}-{4}" -f `
            $hex.Substring(0,8), $hex.Substring(8,4), $hex.Substring(12,4), `
            $hex.Substring(16,4), $hex.Substring(20,12)
        return [Guid]::Parse($withDashes)
    }
    throw "UniqueId invalido: $raw"
}

try {
    $uniqueGuid = ConvertTo-GuidSafe $uniqueIdRaw
} catch {
    Write-Host "FALHA: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$ctx = Get-PnPContext
$file = $ctx.Web.GetFileById($uniqueGuid)
$ctx.Load($file)
try {
    $ctx.ExecuteQuery()
} catch {
    Write-Host "FALHA: GetFileById: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$serverRelativeUrl = [string]$file.ServerRelativeUrl
$nomeRemoto = [string]$file.Name
if (-not $serverRelativeUrl) {
    Write-Host "FALHA: ServerRelativeUrl vazio." -ForegroundColor Red
    exit 1
}

$idx = $serverRelativeUrl.LastIndexOf("/")
$pasta = $serverRelativeUrl.Substring(0, $idx)
$sitePath = ([Uri]$siteUrl).AbsolutePath.TrimEnd("/")
if ($sitePath -and $pasta.StartsWith($sitePath, [System.StringComparison]::OrdinalIgnoreCase)) {
    $pasta = $pasta.Substring($sitePath.Length).TrimStart("/")
}
Write-Host "Pasta: $pasta nome=$nomeRemoto" -ForegroundColor Cyan

$tempDir = Join-Path $env:TEMP ("suite-cat-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$tempFile = Join-Path $tempDir $nomeRemoto
Copy-Item -Path $arquivoLocal -Destination $tempFile -Force

try {
    Add-PnPFile -Path $tempFile -Folder $pasta | Out-Null
} catch {
    Write-Host "FALHA: Add-PnPFile: $($_.Exception.Message)" -ForegroundColor Red
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

$check = Get-PnPFile -Url "$pasta/$nomeRemoto" -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "SUCESSO: $pasta/$nomeRemoto" -ForegroundColor Green
    exit 0
}
Write-Host "FALHA: arquivo nao encontrado apos upload." -ForegroundColor Red
exit 1
