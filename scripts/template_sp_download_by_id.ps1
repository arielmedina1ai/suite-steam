# ============================================================
# SCRIPT: Download por UniqueId (download.aspx?UniqueId=...)
# Placeholders: {{SITE_URL}} {{PASTA_DESTINO}} {{NOME_ARQUIVO}} {{UNIQUE_ID}}
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
$pastaDestino = "{{PASTA_DESTINO}}"
$nomeArquivo  = "{{NOME_ARQUIVO}}"
$uniqueIdRaw  = "{{UNIQUE_ID}}"

Write-Host "Site: $siteUrl" -ForegroundColor Cyan
Write-Host "UniqueId recebido: $uniqueIdRaw" -ForegroundColor Cyan

Write-Host "Conectando ao SharePoint (WebLogin)..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

if (-not (Test-Path -Path $pastaDestino)) {
    New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
}

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

Write-Host "UniqueId Guid: $uniqueGuid" -ForegroundColor Cyan

$serverRelativeUrl = $null
$nomeRemoto = $null

# --- CSOM GetFileById ---
try {
    $ctx = Get-PnPContext
    $file = $ctx.Web.GetFileById($uniqueGuid)
    $ctx.Load($file)
    $ctx.ExecuteQuery()
    $serverRelativeUrl = [string]$file.ServerRelativeUrl
    $nomeRemoto = [string]$file.Name
    Write-Host "CSOM OK: $serverRelativeUrl (nome=$nomeRemoto)" -ForegroundColor DarkGreen
} catch {
    Write-Host "CSOM GetFileById falhou: $($_.Exception.Message)" -ForegroundColor Yellow
}

# --- REST GetFileById ---
if (-not $serverRelativeUrl) {
    try {
        $url = "_api/web/GetFileById('{0}')?`$select=Name,ServerRelativeUrl,Exists" -f $uniqueGuid
        $meta = Invoke-PnPSPRestMethod -Url $url
        Write-Host ("REST: " + ($meta | ConvertTo-Json -Depth 5 -Compress)) -ForegroundColor DarkGray
        if ($meta.ServerRelativeUrl) {
            $serverRelativeUrl = [string]$meta.ServerRelativeUrl
            $nomeRemoto = [string]$meta.Name
        } elseif ($meta.d -and $meta.d.ServerRelativeUrl) {
            $serverRelativeUrl = [string]$meta.d.ServerRelativeUrl
            $nomeRemoto = [string]$meta.d.Name
        }
    } catch {
        Write-Host "REST GetFileById falhou: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

if (-not $nomeArquivo -or $nomeArquivo.Trim() -eq "") {
    $nomeArquivo = $nomeRemoto
}
if (-not $nomeArquivo -or $nomeArquivo.Trim() -eq "") {
    $nomeArquivo = "catalog.json"
}

$caminhoCompleto = Join-Path $pastaDestino $nomeArquivo

if (-not $serverRelativeUrl) {
    Write-Host "FALHA: nao foi possivel obter ServerRelativeUrl do UniqueId." -ForegroundColor Red
    Write-Host "Site: $siteUrl" -ForegroundColor Red
    Write-Host "UniqueId: $uniqueGuid" -ForegroundColor Red
    Write-Host "Possiveis causas:" -ForegroundColor Yellow
    Write-Host "  1) O UniqueId nao e de um arquivo (pode ser pasta/item)." -ForegroundColor Yellow
    Write-Host "  2) O site_url esta incompleto (confira /teams/xxx)." -ForegroundColor Yellow
    Write-Host "  3) Sem permissao no arquivo apos o login." -ForegroundColor Yellow
    Write-Host "Alternativa: use o link de compartilhamento /:u:/r/.../catalog.json no remote_url." -ForegroundColor Yellow
    exit 1
}

Write-Host "Baixando: $serverRelativeUrl -> $caminhoCompleto" -ForegroundColor Cyan

# Get-PnPFile
try {
    Get-PnPFile -Url $serverRelativeUrl -Path $pastaDestino -Filename $nomeArquivo -AsFile -Force -ErrorAction Stop
} catch {
    Write-Host "Get-PnPFile falhou: $($_.Exception.Message)" -ForegroundColor Yellow
}

# OpenBinaryDirect se ainda nao baixou
if (-not (Test-Path $caminhoCompleto)) {
    try {
        $ctx = Get-PnPContext
        $bin = [Microsoft.SharePoint.Client.File]::OpenBinaryDirect($ctx, $serverRelativeUrl)
        $fs = [System.IO.File]::Create($caminhoCompleto)
        $bin.Stream.CopyTo($fs)
        $fs.Close()
        $bin.Dispose()
        Write-Host "OpenBinaryDirect OK" -ForegroundColor DarkGreen
    } catch {
        Write-Host "OpenBinaryDirect falhou: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

if (Test-Path $caminhoCompleto) {
    $len = (Get-Item $caminhoCompleto).Length
    Write-Host "SUCESSO: $caminhoCompleto ($len bytes)" -ForegroundColor Green
    exit 0
}

Write-Host "FALHA: arquivo nao encontrado apos as tentativas de download." -ForegroundColor Red
exit 1
