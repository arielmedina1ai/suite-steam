# ============================================================
# SCRIPT: Upload automatico gerado dinamicamente
# Placeholders: {{SITE_URL}} {{ARQUIVO_LOCAL}} {{NOME_ARQUIVO}} {{CAMINHO_SP}}
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
$arquivoLocal = "{{ARQUIVO_LOCAL}}"
$nomeArquivo  = "{{NOME_ARQUIVO}}"
$caminhoSP    = "{{CAMINHO_SP}}"

# --- CONECTA AO SHAREPOINT ---
Write-Host "Conectando ao SharePoint..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue

# --- VERIFICA SE O ARQUIVO LOCAL EXISTE ---
if (-not (Test-Path -Path $arquivoLocal)) {
    Write-Host "FALHA: Arquivo local nao encontrado: $arquivoLocal" -ForegroundColor Red
    exit 1
}

# --- DESCOBERTA DINAMICA DO CAMINHO DA PASTA ---
Write-Host "Localizando pasta de destino..." -ForegroundColor Cyan

$partes = $caminhoSP -split "/"
$caminhoAtual = $partes[0]

foreach ($parte in $partes[1..($partes.Length - 1)]) {
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

Write-Host "Pasta resolvida: $caminhoAtual" -ForegroundColor Green

# --- CRIA A PASTA NO SHAREPOINT SE NAO EXISTIR ---
try {
    Get-PnPFolder -Url $caminhoAtual -ErrorAction Stop | Out-Null
    Write-Host "Pasta ja existe no SharePoint." -ForegroundColor DarkGreen
} catch {
    Write-Host "Pasta nao encontrada. Criando: $caminhoAtual ..." -ForegroundColor Yellow
    $nomePastaNova = $caminhoAtual.Split("/")[-1]
    $pastaPai      = $caminhoAtual.Substring(0, $caminhoAtual.LastIndexOf("/"))
    Add-PnPFolder -Name $nomePastaNova -Folder $pastaPai
    Write-Host "Pasta criada com sucesso!" -ForegroundColor Green
}

# --- FAZ O UPLOAD ---
Write-Host "Enviando $nomeArquivo ..." -ForegroundColor Cyan
Add-PnPFile `
    -Path $arquivoLocal `
    -Folder $caminhoAtual

# --- VERIFICA RESULTADO ---
$arquivoSP = Get-PnPFile -Url "$caminhoAtual/$nomeArquivo" -ErrorAction SilentlyContinue
if ($arquivoSP) {
    Write-Host "SUCESSO: Arquivo enviado para $caminhoAtual/$nomeArquivo" -ForegroundColor Green
} else {
    Write-Host "FALHA: Arquivo nao encontrado apos upload." -ForegroundColor Red
    exit 1
}
