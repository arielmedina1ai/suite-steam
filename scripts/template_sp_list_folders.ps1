# ============================================================
# SCRIPT: Lista pastas imediatas sob um caminho SharePoint
# Placeholders: {{SITE_URL}} {{CAMINHO_SP}} {{OUT_FILE}}
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

$siteUrl   = "{{SITE_URL}}"
$caminhoSP = "{{CAMINHO_SP}}"
$outFile   = "{{OUT_FILE}}"

Write-Host "Conectando ao SharePoint..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

Write-Host "Listando pastas em $caminhoSP ..." -ForegroundColor Cyan

$nomes = New-Object System.Collections.Generic.List[string]
try {
    $itens = $null
    try {
        $itens = Get-PnPFolderItem -FolderSiteRelativeUrl $caminhoSP -ItemType Folder -ErrorAction Stop
    } catch {
        $itens = Get-PnPFolderItem -FolderSiteRelativeUrl $caminhoSP -ErrorAction Stop
    }
    foreach ($it in @($itens)) {
        $isFolder = $false
        if ($null -ne $it.PSObject.Properties['FSObjType'] -and [int]$it.FSObjType -eq 1) {
            $isFolder = $true
        }
        $typeName = $it.GetType().Name
        if ($typeName -match 'Folder') { $isFolder = $true }
        if (-not $isFolder -and $it.PSObject.Properties['TypedObject']) {
            if ($it.TypedObject.GetType().Name -match 'Folder') { $isFolder = $true }
        }
        if ($isFolder -and $it.Name) {
            $nomes.Add([string]$it.Name)
        }
    }
} catch {
    Write-Host "FALHA: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$payload = @{ folders = @($nomes) } | ConvertTo-Json -Compress
Set-Content -Path $outFile -Value $payload -Encoding UTF8
Write-Host "SUCESSO: $($nomes.Count) pasta(s)" -ForegroundColor Green
