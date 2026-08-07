# Configuração do SharePoint

É necessário Windows PowerShell compatível com `SharePointPnPPowerShellOnline`. O startup deve executar o check antes do provedor e liberar a sincronização apenas em `OK` ou `REPAIRED_OK`.

Sem internet, o check funciona e o reparo informa falha. DLL bloqueada produz `DEPENDENCY_INACCESSIBLE`; múltiplas versões, `MULTIPLE_VERSIONS`; ausência, `MODULE_NOT_FOUND`; falha de import, `IMPORT_FAILED` ou `ASSEMBLY_CONFLICT`; permissão insuficiente, `PERMISSION_DENIED`. Cada operação usa processo separado e o aplicativo não encerra PowerShell externo.