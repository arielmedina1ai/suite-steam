# ============================================================
# SCRIPT: Download automatico gerado dinamicamente
# Placeholders: {{SITE_URL}} {{PASTA_DESTINO}} {{NOME_ARQUIVO}} {{CAMINHO_SP}}
# ============================================================

$env:PNPLEGACYMESSAGE = 'false'

# --- INSTALA MODULO SE NAO EXISTIR ---
if (-not (Get-Module -ListAvailable -Name SharePointPnPPowerShellOnline)) {
    Write-Host "Instalando modulo SharePointPnPPowerShellOnline..." -ForegroundColor Yellow
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    Install-Module SharePointPnPPowerShellOnline -Scope CurrentUser -Force -AllowClobber
    Write-Host "Modulo instalado com sucesso!" -ForegroundColor Green
}

Import-Module SharePointPnPPowerShellOnline -Force -WarningAction SilentlyContinue

# --- VERIFICA SE O MODULO CARREGOU ---
if (-not (Get-Command Connect-PnPOnline -ErrorAction SilentlyContinue)) {
    Write-Host "FALHA: Modulo nao carregado. Feche e reabra o PowerShell e tente novamente." -ForegroundColor Red
    exit 1
}

$siteUrl      = "{{SITE_URL}}"
$pastaDestino = "{{PASTA_DESTINO}}"
$nomeArquivo  = "{{NOME_ARQUIVO}}"
$caminhoSP    = "{{CAMINHO_SP}}"

# --- CONECTA AO SHAREPOINT ---
Write-Host "Conectando ao SharePoint..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

# --- CRIA PASTA DE DESTINO SE NAO EXISTIR ---
if (-not (Test-Path -Path $pastaDestino)) {
    New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
    Write-Host "Pasta criada: $pastaDestino" -ForegroundColor Green
}

# --- DESCOBERTA DINAMICA DO CAMINHO ---
Write-Host "Localizando arquivo..." -ForegroundColor Cyan

$partes = $caminhoSP -split "/"
$totalPartes = $partes.Length
$partasPasta = $partes[0..($totalPartes - 2)]
$caminhoAtual = $partasPasta[0]

foreach ($parte in $partasPasta[1..($partasPasta.Length - 1)]) {
    $nomeLimpo = $parte -replace '[^a-zA-Z0-9\s\-_]', '*'
    $encontrado = Get-PnPFolderItem -FolderSiteRelativeUrl $caminhoAtual |
                  Where-Object { $_.Name -like "*$nomeLimpo*" } |
                  Select-Object -First 1

    if ($encontrado) {
        $caminhoAtual = "$caminhoAtual/$($encontrado.Name)"
        Write-Host "  v $($encontrado.Name)" -ForegroundColor DarkGreen
    } else {
        $caminhoAtual = "$caminhoAtual/$parte"
        Write-Host "  ? Pasta nao encontrada via busca, usando: $parte" -ForegroundColor Yellow
    }
}

$caminhoFinal = "$caminhoAtual/$nomeArquivo"
Write-Host "Caminho resolvido: $caminhoFinal" -ForegroundColor Green

# --- FAZ O DOWNLOAD ---
Write-Host "Baixando $nomeArquivo ..." -ForegroundColor Cyan
Get-PnPFile `
    -Url $caminhoFinal `
    -Path $pastaDestino `
    -Filename $nomeArquivo `
    -AsFile `
    -Force

# --- VERIFICA RESULTADO ---
$caminhoCompleto = Join-Path $pastaDestino $nomeArquivo
if (Test-Path $caminhoCompleto) {
    Write-Host "SUCESSO: $caminhoCompleto" -ForegroundColor Green
} else {
    Write-Host "FALHA: Arquivo nao encontrado apos download." -ForegroundColor Red
    exit 1
}
