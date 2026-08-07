# Dependências SharePoint

A aplicação usa exclusivamente `SharePointPnPPowerShellOnline` e valida `Microsoft.IdentityModel.Clients.ActiveDirectory.dll` antes da sincronização. O check usa subprocesso PowerShell isolado; o reparo só ocorre com `-Repair` ou política explícita.

```powershell
powershell .\scripts\check_and_resolving_dependencies.ps1
powershell .\scripts\check_and_resolving_dependencies.ps1 -Repair
```

O resultado final é JSON em uma linha. Estados incluem `OK`, `MODULE_NOT_FOUND`, `DEPENDENCY_MISSING`, `IMPORT_FAILED`, `MULTIPLE_VERSIONS`, `REPAIRED_OK`, `REPAIR_FAILED`, `VALIDATION_FAILED` e `UNSUPPORTED_ENVIRONMENT`. A reinstalação usa `CurrentUser`; não há cópia manual da DLL nem encerramento de processos externos.