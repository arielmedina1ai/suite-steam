# Empacota a Suite como SuiteAPPs.exe via flet pack (PyInstaller).
# Uso (na raiz do repo, com venv ativo):
#   .\scripts\build_exe.ps1
# Artefato: dist\SuiteAPPs.exe
# Copie settings.json ao lado do .exe antes de distribuir.

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$IconCandidates = @(
    (Join-Path $Root "assets\branding\window_icon.ico"),
    (Join-Path $Root "assets\branding\window_icon.png"),
    (Join-Path $Root "assets\branding\window_icon.example.png")
)
$Icon = $IconCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$SettingsPath = Join-Path $Root "settings.json"
$ProductVersion = "0.1.0"
if (Test-Path $SettingsPath) {
    try {
        $settings = Get-Content $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($settings.app.version) {
            $ProductVersion = [string]$settings.app.version
        }
    } catch {
        Write-Warning "Nao foi possivel ler app.version de settings.json; usando $ProductVersion"
    }
}

# file-version exige n.n.n.n
$parts = ($ProductVersion -split "[^\d]+" | Where-Object { $_ -ne "" })
while ($parts.Count -lt 4) { $parts += "0" }
$FileVersion = ($parts[0..3] -join ".")

$PackArgs = @(
    "pack",
    "src\main.py",
    "--name", "SuiteAPPs",
    "--product-name", "Suite APPs",
    "--file-description", "Suite Petrobras - hub de aplicativos",
    "--product-version", $ProductVersion,
    "--file-version", $FileVersion,
    "--company-name", "Petrobras",
    "--add-data", "assets;assets",
    "--add-data", "scripts;scripts",
    "--add-data", "settings.example.json;.",
    "--add-data", "catalog.example.json;.",
    "--yes"
)

if ($Icon) {
    $PackArgs += @("--icon", $Icon)
    Write-Host "Icone: $Icon"
} else {
    Write-Warning "Nenhum icone encontrado em assets/branding; o exe usara o padrao."
}

Write-Host "Empacotando SuiteAPPs $ProductVersion ..."
Write-Host "flet $($PackArgs -join ' ')"
& flet @PackArgs
if ($LASTEXITCODE -ne 0) {
    throw "flet pack falhou com codigo $LASTEXITCODE"
}

$Exe = Join-Path $Root "dist\SuiteAPPs.exe"
if (-not (Test-Path $Exe)) {
    throw "Artefato esperado nao encontrado: $Exe"
}

Write-Host ""
Write-Host "OK: $Exe"
Write-Host "Proximo passo: copie settings.json para dist\ (ao lado do exe) antes de testar/distribuir."
Write-Host "No PC destino ainda sao necessarios PowerShell e modulo PnP (SharePoint)."
