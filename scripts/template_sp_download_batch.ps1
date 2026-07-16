# ============================================================
# SCRIPT: Download em lote (1 Connect-PnPOnline, N arquivos)
# Placeholders: {{SITE_URL}} {{PASTA_DESTINO}} {{MANIFEST_PATH}} {{RESULT_PATH}}
#
# Manifest JSON (array):
#   { "id", "tipo": "path"|"unique_id", "nome_arquivo",
#     "caminho_sp"?, "unique_id"? }
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
    Write-Host "FALHA: Modulo nao carregado." -ForegroundColor Red
    exit 1
}

$siteUrl      = "{{SITE_URL}}"
$pastaDestino = "{{PASTA_DESTINO}}"
$manifestPath = "{{MANIFEST_PATH}}"
$resultPath   = "{{RESULT_PATH}}"

if (-not (Test-Path -Path $manifestPath)) {
    Write-Host "FALHA: manifest nao encontrado: $manifestPath" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -Path $pastaDestino)) {
    New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
}

try {
    $itens = Get-Content -Path $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
} catch {
    Write-Host "FALHA: manifest JSON invalido: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if ($null -eq $itens) {
    $itens = @()
} elseif ($itens -isnot [System.Array]) {
    $itens = @($itens)
}

Write-Host "Site: $siteUrl" -ForegroundColor Cyan
Write-Host "Arquivos no lote: $($itens.Count)" -ForegroundColor Cyan
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

function Resolve-CaminhoSp([string]$caminhoSP, [string]$nomeArquivo) {
    $partes = $caminhoSP -split "/"
    $totalPartes = $partes.Length
    if ($totalPartes -lt 2) {
        return $caminhoSP
    }
    $partasPasta = $partes[0..($totalPartes - 2)]
    $caminhoAtual = $partasPasta[0]

    if ($partasPasta.Length -gt 1) {
        foreach ($parte in $partasPasta[1..($partasPasta.Length - 1)]) {
            $nomeLimpo = $parte -replace '[^a-zA-Z0-9\s\-_]', '*'
            $encontrado = Get-PnPFolderItem -FolderSiteRelativeUrl $caminhoAtual |
                          Where-Object { $_.Name -like "*$nomeLimpo*" } |
                          Select-Object -First 1
            if ($encontrado) {
                $caminhoAtual = "$caminhoAtual/$($encontrado.Name)"
            } else {
                $caminhoAtual = "$caminhoAtual/$parte"
            }
        }
    }
    return "$caminhoAtual/$nomeArquivo"
}

function Get-FileByUniqueId([Guid]$uniqueGuid) {
    $serverRelativeUrl = $null
    $nomeRemoto = $null
    try {
        $ctx = Get-PnPContext
        $file = $ctx.Web.GetFileById($uniqueGuid)
        $ctx.Load($file)
        $ctx.ExecuteQuery()
        $serverRelativeUrl = [string]$file.ServerRelativeUrl
        $nomeRemoto = [string]$file.Name
    } catch { }

    if (-not $serverRelativeUrl) {
        try {
            $url = "_api/web/GetFileById('{0}')?`$select=Name,ServerRelativeUrl,Exists" -f $uniqueGuid
            $meta = Invoke-PnPSPRestMethod -Url $url
            if ($meta.ServerRelativeUrl) {
                $serverRelativeUrl = [string]$meta.ServerRelativeUrl
                $nomeRemoto = [string]$meta.Name
            } elseif ($meta.d -and $meta.d.ServerRelativeUrl) {
                $serverRelativeUrl = [string]$meta.d.ServerRelativeUrl
                $nomeRemoto = [string]$meta.d.Name
            }
        } catch { }
    }
    return @{ Url = $serverRelativeUrl; Name = $nomeRemoto }
}

function Save-OpenBinaryDirect([string]$serverRelativeUrl, [string]$destino) {
    $ctx = Get-PnPContext
    $bin = [Microsoft.SharePoint.Client.File]::OpenBinaryDirect($ctx, $serverRelativeUrl)
    $fs = [System.IO.File]::Create($destino)
    $bin.Stream.CopyTo($fs)
    $fs.Close()
    $bin.Dispose()
}

$resultados = New-Object System.Collections.Generic.List[object]
$idx = 0
foreach ($item in $itens) {
    $idx++
    $id = [string]$item.id
    $tipo = [string]$item.tipo
    $nomeArquivo = [string]$item.nome_arquivo
    $ok = $false
    $erro = ""
    $caminhoCompleto = $null

    Write-Host "[$idx/$($itens.Count)] $id ($tipo) -> $nomeArquivo" -ForegroundColor Cyan

    try {
        if (-not $nomeArquivo -or $nomeArquivo.Trim() -eq "") {
            throw "nome_arquivo vazio"
        }
        $caminhoCompleto = Join-Path $pastaDestino $nomeArquivo

        if ($tipo -eq "unique_id") {
            $uniqueGuid = ConvertTo-GuidSafe ([string]$item.unique_id)
            $meta = Get-FileByUniqueId $uniqueGuid
            if (-not $meta.Url) {
                throw "UniqueId sem ServerRelativeUrl"
            }
            try {
                Get-PnPFile -Url $meta.Url -Path $pastaDestino -Filename $nomeArquivo -AsFile -Force -ErrorAction Stop
            } catch {
                Save-OpenBinaryDirect $meta.Url $caminhoCompleto
            }
        } else {
            $caminhoSp = [string]$item.caminho_sp
            if (-not $caminhoSp) { throw "caminho_sp vazio" }
            $caminhoFinal = Resolve-CaminhoSp $caminhoSp $nomeArquivo
            Write-Host "  caminho: $caminhoFinal" -ForegroundColor DarkGray
            Get-PnPFile -Url $caminhoFinal -Path $pastaDestino -Filename $nomeArquivo -AsFile -Force -ErrorAction Stop
        }

        if (Test-Path $caminhoCompleto) {
            $ok = $true
            $len = (Get-Item $caminhoCompleto).Length
            Write-Host "  SUCESSO ($len bytes)" -ForegroundColor DarkGreen
        } else {
            throw "arquivo nao encontrado apos download"
        }
    } catch {
        $erro = $_.Exception.Message
        Write-Host "  FALHA: $erro" -ForegroundColor Yellow
    }

    $resultados.Add([pscustomobject]@{
        id           = $id
        ok           = $ok
        nome_arquivo = $nomeArquivo
        path         = $(if ($ok) { $caminhoCompleto } else { $null })
        error        = $erro
    }) | Out-Null
}

$resultados | ConvertTo-Json -Depth 4 | Set-Content -Path $resultPath -Encoding UTF8
$okCount = @($resultados | Where-Object { $_.ok }).Count
Write-Host "LOTE: $okCount/$($resultados.Count) ok. Resultado: $resultPath" -ForegroundColor Green

# exit 0 mesmo com falhas parciais — Python le o result JSON
exit 0
