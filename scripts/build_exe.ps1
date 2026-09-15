# Empacota o hub como .exe via flet pack (PyInstaller).
# Uso (na raiz do repo, com venv ativo):
#   1. Edite settings.json (app.name, company, exe_name, data_dir, etc.) e assets/branding/
#   2. .\scripts\build_exe.ps1
# Artefato: dist\{app.exe_name}.exe
# Titulo/product-name: app.name
# O settings.json do operador e a fonte; SuiteApps e so o default se o campo vier vazio.

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

$IdentityScript = Join-Path $PSScriptRoot "pack_identity.py"
$Python = $null
foreach ($cmd in @("python", "py", "python3")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $Python = $found.Source
        break
    }
}
if (-not $Python) {
    throw "Python nao encontrado no PATH. Ative o venv antes de .\scripts\build_exe.ps1."
}

$IdentityRaw = & $Python $IdentityScript $SettingsPath
if ($LASTEXITCODE -ne 0 -or -not $IdentityRaw) {
    throw "Falha ao ler app.name / app.exe_name de settings.json."
}
try {
    $identity = $IdentityRaw | ConvertFrom-Json
} catch {
    throw "Nao foi possivel interpretar a identidade do pack a partir de settings.json."
}

$ProductName = [string]$identity.name
$ProductVersion = [string]$identity.version
$ExeName = [string]$identity.exe_name
$CompanyName = [string]$identity.company
if (-not $ProductName) { $ProductName = "SuiteApps" }
if (-not $ExeName) { $ExeName = "SuiteApps" }
if (-not $ProductVersion) { $ProductVersion = "0.1.0" }

Write-Host "settings.json"
Write-Host "  app.name      -> janela / --product-name : $ProductName"
Write-Host "  app.exe_name  -> dist\$ExeName.exe / --name : $ExeName"
Write-Host "  app.version   -> $ProductVersion"
if ($CompanyName) {
    Write-Host "  app.company   -> $CompanyName"
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
    "--hidden-import", "pystray",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL.Image",
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

$DistDir = Join-Path $Root "dist"
$Exe = Join-Path $DistDir "$ExeName.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    $match = Get-ChildItem -LiteralPath $DistDir -Filter "*.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -ieq $ExeName } |
        Select-Object -First 1
    if ($match) {
        # NTFS e case-insensitive: forca o casing exato de app.exe_name
        $stage = Join-Path $DistDir ("__rename_" + [guid]::NewGuid().ToString("N") + ".exe")
        Rename-Item -LiteralPath $match.FullName -NewName ([IO.Path]::GetFileName($stage))
        Rename-Item -LiteralPath $stage -NewName "$ExeName.exe"
    }
}

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Artefato esperado nao encontrado: $Exe (confira app.exe_name no settings.json)"
}

Write-Host ""
Write-Host "OK: $Exe"
Write-Host "O settings.json do build ja esta dentro do .exe (app.name na janela; app.exe_name no arquivo)."
Write-Host "No PC destino ainda sao necessarios PowerShell e modulo PnP (SharePoint)."
