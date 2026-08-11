# Pendências da verificação e reparo do SharePoint

## Estado atual

A branch `feature/check-and-resolving-dependencies` já contém:

- `scripts/check_and_resolving_dependencies.ps1`;
- `scripts/reparar_pnp.ps1`;
- `src/dependency_check.py`;
- testes básicos em `tests/test_dependency_check.py`;
- correção dos exports em `src/catalog/__init__.py`;
- remoção do erro fatal `RuntimeError: REPAIR_FAILED` no import de `catalog`.

A aplicação deve iniciar sem travar no import. O reparo ainda não está totalmente integrado ao fluxo real de sincronização do SharePoint.

## Restrições obrigatórias

- Usar exclusivamente `SharePointPnPPowerShellOnline`.
- Manter `Connect-PnPOnline -UseWebLogin`.
- Não migrar para outro módulo.
- Não copiar DLL manualmente.
- Não baixar DLL de fonte desconhecida.
- Não executar `Stop-Process` em PowerShells externos.
- Não reinstalar o módulo a cada abertura.
- Não embutir o módulo no `.exe`.
- Não registrar senhas, tokens, cookies, client secrets ou URLs com segredo.
- Não alterar o contrato do catálogo sem necessidade.
- Preservar cache local existente.

## 1. `src/catalog/__init__.py`

### Estado esperado

Não deve executar validação ou reparo no momento do import. Deve apenas reexportar o provider:

```python
from .provider import (
    CatalogProvider,
    CatalogSyncResult,
    LocalCatalogProvider,
    SharePointCatalogProvider,
)

__all__ = [
    "CatalogProvider",
    "CatalogSyncResult",
    "LocalCatalogProvider",
    "SharePointCatalogProvider",
]
```

Se `src/main.py` usa `get_default_provider`, exporte somente se a função realmente existir em `provider.py`. Não importe `RemoteCatalogProvider` se a classe não existir.

## 2. `scripts/reparar_pnp.ps1`

O script já existe e deve:

1. Definir `$ErrorActionPreference = 'Stop'`.
2. Definir `$ModuleName = 'SharePointPnPPowerShellOnline'`.
3. Remover o módulo da sessão atual, sem confiar que isso descarrega assemblies.
4. Executar em subprocesso separado chamado pelo Python.
5. Rodar `Uninstall-Module -Name $ModuleName -AllVersions -Force`.
6. Instalar `NuGet` em `CurrentUser` quando necessário.
7. Executar:

```powershell
Install-Module -Name $ModuleName -Scope CurrentUser -Force -AllowClobber -SkipPublisherCheck
```

8. Importar o módulo com `-Force`.
9. Verificar `Get-Command Connect-PnPOnline`.
10. Retornar `REPAIR_OK` com código `0` apenas após validação.
11. Retornar `REPAIR_FAILED` com código `1` em falha.

O script não deve apagar diretórios arbitrários se `Uninstall-Module` falhar. Registre caminhos encontrados e informe falha controlada.

## 3. `src/services/sharepoint_manager.py`

### 3.1 Executar PowerShell isoladamente

Adicionar helper semelhante:

```python
def _run_powershell(script_path: str, timeout: int = 300) -> tuple[int, str, str]:
    processo = subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = processo.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait()
        return 124, "", "Timeout ao executar script PowerShell."
    return processo.returncode, stdout, stderr
```

### 3.2 Detectar erro de dependência

Adicionar:

```python
def _is_pnp_dependency_error(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    markers = [
        "microsoft.identitymodel.clients.activedirectory",
        "sharepointpnppowershellonline",
        "connect-pnponline",
        "import-module",
        "could not load file or assembly",
        "assembly with same name",
        "filenotfoundexception",
        "is not recognized",
        "nao e reconhecido",
        "repair_failed",
    ]
    return any(marker in text for marker in markers)
```

Não usar falha genérica de rede, autenticação ou permissão para reinstalar o módulo.

### 3.3 Reparo automático

Adicionar:

```python
def _reparar_dependencia_pnp() -> tuple[bool, str]:
    script = _scripts_dir() / "reparar_pnp.ps1"
    if not script.exists():
        return False, "Script de reparo não encontrado."

    code, stdout, stderr = _run_powershell(str(script.resolve()), timeout=300)
    log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)

    if code == 0 and "REPAIR_OK" in stdout:
        return True, "Dependência PnP reparada com sucesso."
    return False, f"Reparo PnP falhou. {log}"
```

### 3.4 Retry após falha

Dentro de `baixar_do_sharepoint`:

1. Executar a tentativa normal com o template existente.
2. Se `result.ok` for verdadeiro, retornar sem reparo.
3. Se falhar e `_is_pnp_dependency_error(result.stdout, result.stderr)` for verdadeiro:
   - registrar início do reparo;
   - chamar `_reparar_dependencia_pnp()`;
   - aguardar o término;
   - somente se retornar sucesso, repetir a tentativa de download em novo subprocesso.
4. Se o retry falhar, retornar o resultado final com mensagem amigável.
5. Se o erro não for de dependência, não executar o reparo.

Não criar loop de retry. Apenas uma tentativa de reparo e uma nova tentativa de download.

## 4. `src/catalog/provider.py`

### Fallback seguro

Quando `baixar_do_sharepoint()` falhar:

1. Tentar `_load_cached_catalog()`.
2. Se houver cache, retornar com:
   - `from_cache=True`;
   - `ok=False`;
   - mensagem amigável indicando uso do cache.
3. Se não houver cache, carregar o catálogo local de exemplo com `LocalCatalogProvider()`.
4. Retornar mensagem amigável, sem traceback bruto e sem fechar o app.

O formato exato do `CatalogSyncResult` deve ser preservado conforme o projeto atual. Se o campo for `apps` em vez de `catalog`, use o contrato existente.

## 5. Empacotamento `.exe`

Garantir que a pasta `scripts` entre no bundle e que `_scripts_dir()` resolva corretamente o caminho quando a aplicação estiver congelada:

- desenvolvimento: raiz do repositório + `scripts`;
- frozen: diretório extraído pelo empacotador + `scripts`.

O reparo deve localizar `scripts/reparar_pnp.ps1` tanto em dev quanto no `.exe`.

## 6. Logs

Registrar apenas dados técnicos seguros:

- executável PowerShell;
- versão do PowerShell;
- caminho do script;
- versões/caminhos do módulo;
- presença da DLL;
- início e fim do reparo;
- duração;
- status final.

Nunca registrar credenciais, tokens, cookies, certificados ou parâmetros sensíveis.

## 7. Documentação

Atualizar os arquivos existentes:

- `README.md`;
- `CONFIGURACAO.md`.

Documentar:

- uso exclusivo de `SharePointPnPPowerShellOnline`;
- reparo condicional e automático somente após falha de dependência;
- uso de subprocessos PowerShell isolados;
- ausência de encerramento de processos externos;
- necessidade de PowerShell Gallery quando reinstalação for necessária;
- comportamento offline;
- uso de cache local;
- fallback para catálogo de exemplo;
- como executar o script manualmente:

```powershell
powershell .\scripts\reparar_pnp.ps1
```

## 8. Testes obrigatórios

Criar ou atualizar testes para:

1. download normal bem-sucedido, sem reparo;
2. erro não relacionado à dependência, sem reparo;
3. erro de dependência com `REPAIR_OK`, seguido de retry bem-sucedido;
4. erro de dependência com `REPAIR_FAILED`, seguido de cache;
5. sem cache, fallback para catálogo local;
6. timeout do PowerShell;
7. script de reparo ausente;
8. `powershell.exe` ausente;
9. nenhum processo externo encerrado;
10. aplicação não fecha no startup;
11. `.exe` localiza `reparar_pnp.ps1`;
12. ausência de credenciais em logs.

Se não houver infraestrutura completa, adicionar testes unitários com mocks e documentar testes manuais executados.

## 9. Comandos de validação local

Na máquina Windows:

```powershell
git checkout feature/check-and-resolving-dependencies
git pull origin feature/check-and-resolving-dependencies
python -m pytest
python src/main.py
.\scripts\build_exe.ps1
```

Depois de gerar o `.exe`:

1. Testar com módulo funcionando: deve abrir e sincronizar sem reparo.
2. Testar com módulo ausente: deve executar reparo apenas quando a sincronização detectar erro de dependência.
3. Testar com DLL ausente/corrompida: deve reparar e tentar novamente.
4. Desconectar a internet antes do reparo: deve falhar de forma controlada e abrir com cache.
5. Executar sem permissão administrativa: deve tentar `CurrentUser` e não pedir elevação silenciosa.

## 10. Critérios de aceite

A funcionalidade estará pronta quando:

1. O app iniciar sem `RuntimeError` causado por dependência.
2. O reparo só ocorrer após falha relacionada à dependência.
3. `reparar_pnp.ps1` for executado em subprocesso isolado.
4. O retry de download ocorrer em outro subprocesso.
5. `REPAIR_OK` só for retornado após import e verificação de `Connect-PnPOnline`.
6. Falha final não derrubar o app.
7. Cache local for usado quando disponível.
8. Catálogo local de exemplo for usado quando não houver cache.
9. O `.exe` encontrar o script de reparo.
10. PowerShells externos não forem encerrados.
11. Logs não vazarem credenciais.
12. README e CONFIGURACAO estiverem atualizados.
13. Testes unitários relevantes passarem.
14. Build do `.exe` for validado em Windows.
15. A branch tiver diff revisado e Pull Request aberto para `main`.

## 11. Arquivos que precisam de atenção

- `src/services/sharepoint_manager.py`
- `src/catalog/provider.py`
- `scripts/reparar_pnp.ps1`
- `README.md`
- `CONFIGURACAO.md`
- `tests/`
- `scripts/build_exe.ps1` ou configuração de empacotamento

## 12. Notas para a próxima IA

Não substitua `sharepoint_manager.py` ou `provider.py` por versões reconstruídas sem preservar o código atual. Leia os arquivos, aplique patch cirúrgico e preserve:

- parsing de links SharePoint;
- suporte a `download.aspx?UniqueId=`;
- WebLogin;
- cache local;
- downloads de apps e imagens;
- upload opcional;
- contrato atual de `CatalogSyncResult`.

Não abrir Pull Request até executar a validação de sintaxe Python/PowerShell e o teste prático no `.exe`.