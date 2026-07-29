# Instala dependencias de requirements.txt usando pip.local.json (mirror corporativo).
# Uso (na raiz do repo):
#   copy pip.local.example.json pip.local.json
#   # edite index_url e trusted_hosts
#   .\scripts\install_deps.ps1
#
# Prioridade dos parametros:
#   1. pip.local.json (raiz do repo)
#   2. fallback publico: pypi.org + files.pythonhosted.org (sem --index-url)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$PipCmd = @()
if (Test-Path $VenvPython) {
    $PipCmd = @($VenvPython, "-m", "pip")
    Write-Host "Usando pip do .venv"
} else {
    $PipCmd = @("python", "-m", "pip")
    Write-Host "Usando python do PATH (crie .venv se preferir isolamento)"
}

$ConfigPath = Join-Path $Root "pip.local.json"
$IndexUrl = $null
$TrustedHosts = @("pypi.org", "files.pythonhosted.org")

if (Test-Path $ConfigPath) {
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.index_url -and [string]$cfg.index_url.Trim()) {
        $IndexUrl = [string]$cfg.index_url.Trim()
    }
    if ($null -ne $cfg.trusted_hosts) {
        $hosts = @($cfg.trusted_hosts | ForEach-Object { [string]$_.Trim() } | Where-Object { $_ })
        if ($hosts.Count -gt 0) {
            $TrustedHosts = $hosts
        }
    }
    Write-Host "Config: $ConfigPath"
} else {
    Write-Warning "pip.local.json nao encontrado; usando fallback publico. Copie pip.local.example.json -> pip.local.json para o mirror interno."
}

$Args = @("install", "-r", "requirements.txt")
if ($IndexUrl) {
    $Args += @("--index-url", $IndexUrl)
    Write-Host "index-url: $IndexUrl"
}
foreach ($h in $TrustedHosts) {
    $Args += @("--trusted-host", $h)
    Write-Host "trusted-host: $h"
}

Write-Host "pip $($Args -join ' ')"
& $PipCmd[0] $PipCmd[1..($PipCmd.Length - 1)] @Args
if ($LASTEXITCODE -ne 0) {
    throw "pip install falhou com codigo $LASTEXITCODE"
}

Write-Host "OK: dependencias instaladas."
