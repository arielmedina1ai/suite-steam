# Empacota a Suite como .exe via flet pack (PyInstaller).
# Uso (na raiz do repo, com venv ativo):
#   1. Edite settings.json (app.name, company, exe_name, data_dir, etc.) e assets/branding/
#   2. .\scripts\build_exe.ps1
# Artefato: dist\{exe_name}.exe (settings.json embutido no bundle)

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
if (-not (Test-Path $SettingsPath)) {
    throw "settings.json nao encontrado. O desenvolvedor deve criar/editar settings.json antes do build (copie de settings.example.json)."
}

$ProductName = "Suite"
$ProductVersion = "0.1.0"
$ExeName = "SuiteAPPs"
$CompanyName = ""
try {
    $settings = Get-Content $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.app.name) {
        $ProductName = [string]$settings.app.name
    }
    if ($settings.app.version) {
        $ProductVersion = [string]$settings.app.version
    }
    if ($settings.app.exe_name) {
        $ExeName = [string]$settings.app.exe_name
    }
    if ($settings.app.company) {
        $CompanyName = [string]$settings.app.company
    }
} catch {
    Write-Warning "Nao foi possivel ler settings.json completamente; usando defaults."
}

# Sanitiza nome do exe (sem path / extensao)
$ExeName = ($ExeName -replace '[\\/:*?"<>|]', "").Trim().Trim(".")
if ($ExeName.ToLower().EndsWith(".exe")) {
    $ExeName = $ExeName.Substring(0, $ExeName.Length - 4)
}
if (-not $ExeName) {
    $ExeName = "SuiteAPPs"
}

# file-version exige n.n.n.n
$parts = ($ProductVersion -split "[^\d]+" | Where-Object { $_ -ne "" })
while ($parts.Count -lt 4) { $parts += "0" }
$FileVersion = ($parts[0..3] -join ".")

$FileDescription = "$ProductName - hub de aplicativos"

$PackArgs = @(
    "pack",
    "src\main.py",
    "--name", $ExeName,
    "--product-name", $ProductName,
    "--file-description", $FileDescription,
    "--product-version", $ProductVersion,
    "--file-version", $FileVersion,
    "--add-data", "assets;assets",
    "--add-data", "scripts;scripts",
    "--add-data", "settings.json;.",
    "--add-data", "settings.example.json;.",
    "--add-data", "catalog.example.json;.",
    "--yes"
)

if ($CompanyName) {
    $PackArgs += @("--company-name", $CompanyName)
}

if ($Icon) {
    $PackArgs += @("--icon", $Icon)
    Write-Host "Icone: $Icon"
} else {
    Write-Warning "Nenhum icone encontrado em assets/branding; o exe usara o padrao."
}

Write-Host "Empacotando $ExeName $ProductVersion ($ProductName) ..."
Write-Host "flet $($PackArgs -join ' ')"
& flet @PackArgs
if ($LASTEXITCODE -ne 0) {
    throw "flet pack falhou com codigo $LASTEXITCODE"
}

$Exe = Join-Path $Root "dist\$ExeName.exe"
if (-not (Test-Path $Exe)) {
    throw "Artefato esperado nao encontrado: $Exe"
}

Write-Host ""
Write-Host "OK: $Exe"
Write-Host "O settings.json do build ja esta dentro do .exe; o usuario final nao precisa de arquivo ao lado."
Write-Host "No PC destino ainda sao necessarios PowerShell e modulo PnP (SharePoint)."
