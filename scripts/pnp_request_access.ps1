# Helper embutido nos templates de download (mesma sessao WebLogin).
# Experimento: pedido automatico de acesso ao SITE apos Access Denied.
# Pode falhar se o site nao tiver solicitacoes de acesso habilitadas.

function Test-SuiteAccessDenied([string]$msg) {
    $t = ([string]$msg).ToLowerInvariant()
    return ($t -match '0x80070005' -or $t -match 'access is denied' -or $t -match 'acesso negado')
}

function Request-SuiteAccess([string]$SiteUrl) {
    $motivo = 'Suite: pedido automatico de acesso apos recusa no download do catalogo/arquivo.'
    $erros = @()

    try {
        $absUrl = '{0}/_api/web/requestaccess' -f $SiteUrl.TrimEnd('/')
        $null = Invoke-PnPSPRestMethod -Url $absUrl -Method Post -Content $motivo -ErrorAction Stop
        Write-Host 'ACCESS_REQUEST_OK'
        return
    } catch {
        $erros += ('rest_texto: ' + $_.Exception.Message)
    }

    try {
        $absUrl = '{0}/_api/web/requestaccess' -f $SiteUrl.TrimEnd('/')
        $body = @{ message = $motivo }
        $null = Invoke-PnPSPRestMethod -Url $absUrl -Method Post -Content $body -ErrorAction Stop
        Write-Host 'ACCESS_REQUEST_OK'
        return
    } catch {
        $erros += ('rest_objeto: ' + $_.Exception.Message)
    }

    Write-Host ('ACCESS_REQUEST_FAILED: ' + ($erros -join ' | '))
}
