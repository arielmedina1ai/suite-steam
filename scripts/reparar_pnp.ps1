[CmdletBinding()]
$ErrorActionPreference = 'Stop'
$env:PNPLEGACYMESSAGE = 'false'
$ModuleName = 'SharePointPnPPowerShellOnline'

Write-Host 'Reparando a dependência do SharePoint...' -ForegroundColor Yellow

try {
    if (-not (Get-Command Uninstall-Module -ErrorAction SilentlyContinue)) {
        throw 'Uninstall-Module não está disponível neste Windows PowerShell.'
    }
    if (-not (Get-Command Install-Module -ErrorAction SilentlyContinue)) {
        throw 'Install-Module não está disponível neste Windows PowerShell.'
    }
    Uninstall-Module -Name $ModuleName -AllVersions -Force -ErrorAction SilentlyContinue
    if (Get-Command Install-PackageProvider -ErrorAction SilentlyContinue) {
        Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    }
    Install-Module -Name $ModuleName -Scope CurrentUser -Force -AllowClobber -SkipPublisherCheck -ErrorAction Stop
    Import-Module -Name $ModuleName -Force -ErrorAction Stop
    if (-not (Get-Command Connect-PnPOnline -ErrorAction SilentlyContinue)) {
        throw 'O módulo foi instalado, mas Connect-PnPOnline não ficou disponível.'
    }
    Write-Output 'REPAIR_OK'
    exit 0
} catch {
    Write-Error ('REPAIR_FAILED: ' + $_.Exception.Message)
    exit 1
}