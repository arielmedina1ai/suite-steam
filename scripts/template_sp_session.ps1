# ============================================================
# SCRIPT: Uma sessao PnP (1 Connect-PnPOnline -UseWebLogin)
# Placeholders: {{SITE_URL}} {{CONTROL_DIR}}
#
# Protocolo (arquivos em CONTROL_DIR):
#   ready.txt  — sessao autenticada
#   cmd.json   — comando { op, site_url?, ... }
#   ack.json   — resposta { ok, error?, path? }
#   quit       — encerra
# ============================================================

$env:PNPLEGACYMESSAGE = 'false'
$ErrorActionPreference = "Continue"

if (-not (Get-Module -ListAvailable -Name SharePointPnPPowerShellOnline)) {
    Write-Host "Instalando modulo SharePointPnPPowerShellOnline..." -ForegroundColor Yellow
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser | Out-Null
    Install-Module SharePointPnPPowerShellOnline -Scope CurrentUser -Force -AllowClobber
}

Import-Module SharePointPnPPowerShellOnline -Force -WarningAction SilentlyContinue

if (-not (Get-Command Connect-PnPOnline -ErrorAction SilentlyContinue)) {
    Write-Host "FALHA: Modulo nao carregado." -ForegroundColor Red
    exit 1
}

$siteUrl    = "{{SITE_URL}}"
$controlDir = "{{CONTROL_DIR}}"

if (-not (Test-Path -Path $controlDir)) {
    New-Item -ItemType Directory -Path $controlDir -Force | Out-Null
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

function Resolve-CaminhoSp([string]$caminhoSP, [string]$nomeArquivo) {
    $partes = $caminhoSP -split "/"
    $totalPartes = $partes.Length
    if ($totalPartes -lt 2) {
        if ($nomeArquivo) { return "$caminhoSP/$nomeArquivo" }
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
    if ($nomeArquivo) { return "$caminhoAtual/$nomeArquivo" }
    return $caminhoAtual
}

function Resolve-PastaSp([string]$caminhoSP) {
    $partes = @($caminhoSP -split "/" | Where-Object { $_ })
    if ($partes.Count -eq 0) { return $caminhoSP }
    $caminhoAtual = $partes[0]
    if ($partes.Count -gt 1) {
        foreach ($parte in $partes[1..($partes.Length - 1)]) {
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
    return $caminhoAtual
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

function Ensure-Site([string]$url) {
    if (-not $url) { return }
    if ($script:currentSite -eq $url) { return }
    Write-Host "Conectando ao SharePoint..." -ForegroundColor Cyan
    Connect-PnPOnline -Url $url -UseWebLogin -WarningAction SilentlyContinue
    $script:currentSite = $url
}

function Write-Ack($obj) {
    $ack = Join-Path $controlDir "ack.json"
    $tmp = Join-Path $controlDir "ack.json.tmp"
    ($obj | ConvertTo-Json -Compress -Depth 6) | Set-Content -Path $tmp -Encoding UTF8
    Move-Item -Path $tmp -Destination $ack -Force
}

function Invoke-DownloadPath($cmd) {
    $pastaDestino = [string]$cmd.pasta_destino
    $nomeArquivo  = [string]$cmd.nome_arquivo
    $caminhoSP    = [string]$cmd.caminho_sp
    if (-not (Test-Path -Path $pastaDestino)) {
        New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
    }
    $caminhoFinal = Resolve-CaminhoSp $caminhoSP $nomeArquivo
    Get-PnPFile -Url $caminhoFinal -Path $pastaDestino -Filename $nomeArquivo -AsFile -Force -ErrorAction Stop
    $caminhoCompleto = Join-Path $pastaDestino $nomeArquivo
    if (-not (Test-Path $caminhoCompleto)) { throw "arquivo nao encontrado apos download" }
    return $caminhoCompleto
}

function Invoke-DownloadId($cmd) {
    $pastaDestino = [string]$cmd.pasta_destino
    $nomeArquivo  = [string]$cmd.nome_arquivo
    if (-not (Test-Path -Path $pastaDestino)) {
        New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
    }
    $uniqueGuid = ConvertTo-GuidSafe ([string]$cmd.unique_id)
    $meta = Get-FileByUniqueId $uniqueGuid
    if (-not $meta.Url) { throw "UniqueId sem ServerRelativeUrl" }
    if (-not $nomeArquivo -or $nomeArquivo.Trim() -eq "") {
        $nomeArquivo = $meta.Name
    }
    if (-not $nomeArquivo) { $nomeArquivo = "catalog.json" }
    $caminhoCompleto = Join-Path $pastaDestino $nomeArquivo
    try {
        Get-PnPFile -Url $meta.Url -Path $pastaDestino -Filename $nomeArquivo -AsFile -Force -ErrorAction Stop
    } catch {
        Save-OpenBinaryDirect $meta.Url $caminhoCompleto
    }
    if (-not (Test-Path $caminhoCompleto)) { throw "arquivo nao encontrado apos download" }
    return $caminhoCompleto
}

function Invoke-UploadFolder($cmd) {
    $arquivoLocal = [string]$cmd.arquivo_local
    $nomeArquivo  = [string]$cmd.nome_arquivo
    $caminhoSP    = [string]$cmd.caminho_sp
    if (-not (Test-Path -Path $arquivoLocal)) {
        throw "Arquivo local nao encontrado: $arquivoLocal"
    }
    $caminhoAtual = Resolve-PastaSp $caminhoSP
    try {
        Get-PnPFolder -Url $caminhoAtual -ErrorAction Stop | Out-Null
    } catch {
        $nomePastaNova = $caminhoAtual.Split("/")[-1]
        $idx = $caminhoAtual.LastIndexOf("/")
        if ($idx -lt 0) { throw "Pasta pai invalida: $caminhoAtual" }
        $pastaPai = $caminhoAtual.Substring(0, $idx)
        Add-PnPFolder -Name $nomePastaNova -Folder $pastaPai | Out-Null
    }
    Add-PnPFile -Path $arquivoLocal -Folder $caminhoAtual | Out-Null
    $arquivoSP = Get-PnPFile -Url "$caminhoAtual/$nomeArquivo" -ErrorAction SilentlyContinue
    if (-not $arquivoSP) { throw "Arquivo nao encontrado apos upload" }
    return "$caminhoAtual/$nomeArquivo"
}

function Invoke-UploadId($cmd) {
    $arquivoLocal = [string]$cmd.arquivo_local
    if (-not (Test-Path -Path $arquivoLocal)) {
        throw "Arquivo local nao encontrado: $arquivoLocal"
    }
    $uniqueGuid = ConvertTo-GuidSafe ([string]$cmd.unique_id)
    $ctx = Get-PnPContext
    $file = $ctx.Web.GetFileById($uniqueGuid)
    $ctx.Load($file)
    $ctx.ExecuteQuery()
    $serverRelativeUrl = [string]$file.ServerRelativeUrl
    $nomeRemoto = [string]$file.Name
    if (-not $serverRelativeUrl) { throw "ServerRelativeUrl vazio" }
    $idx = $serverRelativeUrl.LastIndexOf("/")
    $pasta = $serverRelativeUrl.Substring(0, $idx)
    $sitePath = ([Uri]$script:currentSite).AbsolutePath.TrimEnd("/")
    if ($sitePath -and $pasta.StartsWith($sitePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $pasta = $pasta.Substring($sitePath.Length).TrimStart("/")
    }
    $tempDir = Join-Path $env:TEMP ("suite-cat-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $tempFile = Join-Path $tempDir $nomeRemoto
    Copy-Item -Path $arquivoLocal -Destination $tempFile -Force
    try {
        Add-PnPFile -Path $tempFile -Folder $pasta | Out-Null
    } finally {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    $check = Get-PnPFile -Url "$pasta/$nomeRemoto" -ErrorAction SilentlyContinue
    if (-not $check) { throw "arquivo nao encontrado apos upload" }
    return "$pasta/$nomeRemoto"
}

function Invoke-DeletePath($cmd) {
    $caminhoSP = [string]$cmd.caminho_sp
    $nomeArquivo = [string]$cmd.nome_arquivo
    $caminhoFinal = if ($nomeArquivo) { Resolve-CaminhoSp $caminhoSP $nomeArquivo } else { $caminhoSP }
    Remove-PnPFile -SiteRelativeUrl $caminhoFinal -Force -ErrorAction Stop
    return $caminhoFinal
}

function Invoke-DeleteId($cmd) {
    $uniqueGuid = ConvertTo-GuidSafe ([string]$cmd.unique_id)
    $meta = Get-FileByUniqueId $uniqueGuid
    if (-not $meta.Url) { throw "UniqueId sem ServerRelativeUrl" }
    try {
        Remove-PnPFile -ServerRelativeUrl $meta.Url -Force -ErrorAction Stop
    } catch {
        Remove-PnPFile -SiteRelativeUrl $meta.Url -Force -ErrorAction Stop
    }
    return $meta.Url
}

Write-Host "Conectando ao SharePoint (WebLogin)..." -ForegroundColor Cyan
Connect-PnPOnline -Url $siteUrl -UseWebLogin -WarningAction SilentlyContinue
$script:currentSite = $siteUrl
"ok" | Set-Content -Path (Join-Path $controlDir "ready.txt") -Encoding ASCII

$quitPath = Join-Path $controlDir "quit"
$cmdPath  = Join-Path $controlDir "cmd.json"

while ($true) {
    if (Test-Path $quitPath) { break }
    if (-not (Test-Path $cmdPath)) {
        Start-Sleep -Milliseconds 200
        continue
    }
    Start-Sleep -Milliseconds 80
    try {
        $raw = Get-Content -Path $cmdPath -Encoding UTF8 -Raw
        $cmd = $raw | ConvertFrom-Json
    } catch {
        Start-Sleep -Milliseconds 120
        continue
    }
    Remove-Item $cmdPath -Force -ErrorAction SilentlyContinue
    $op = [string]$cmd.op
    try {
        if ($cmd.site_url) { Ensure-Site ([string]$cmd.site_url) }
        switch ($op) {
            "download_path" {
                $p = Invoke-DownloadPath $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "download_id" {
                $p = Invoke-DownloadId $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "upload_folder" {
                $p = Invoke-UploadFolder $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "upload_id" {
                $p = Invoke-UploadId $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "delete_path" {
                $p = Invoke-DeletePath $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "delete_id" {
                $p = Invoke-DeleteId $cmd
                Write-Ack @{ ok = $true; path = $p }
            }
            "quit" {
                Write-Ack @{ ok = $true }
                break
            }
            default { throw "op desconhecida: $op" }
        }
    } catch {
        Write-Ack @{ ok = $false; error = $_.Exception.Message }
    }
}

Disconnect-PnPOnline -ErrorAction SilentlyContinue
exit 0
