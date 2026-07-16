# Suite Petrobras

Hub de aplicativos internos no estilo "Steam", desenvolvido em Python + [Flet](https://flet.dev).
A Suite apresenta o setor na tela inicial e, no menu lateral, lista os programas disponiveis
(`.exe`, `.xlsx` e `.xlsm`). Cada aplicativo tem tela de detalhe com imagem, descricao e
Baixar / Instalar / Executar / Desinstalar.

> **Casca configuravel:** repositorio publico sem dados internos. Textos/cores e a URL do
> `catalog.json` ficam no `settings.json` local. O catalogo oficial (apps, versoes, imagens
> e links) vive no **SharePoint** e e sincronizado a cada abertura.
> Veja **[CONFIGURACAO.md](CONFIGURACAO.md)**.

## Recursos

- Catalogo sincronizado do SharePoint (PnP) a cada execucao, com cache local.
- Imagens em cache: so rebaixam se `imagem` ou `imagem_versao` mudarem no catalogo.
- Download/upload de apps via PowerShell + PnP (`Connect-PnPOnline -UseWebLogin`).
- Desinstalar remove arquivos locais e o registro.
- Identidade visual e textos do setor via `settings.json`.

## Estrutura

```
Suite-steam/
  settings.example.json      # modelo (copie p/ settings.json)
  catalog.example.json       # modelo do catalogo para publicar no SharePoint
  CONFIGURACAO.md
  scripts/
    template_sp_download.ps1
    template_sp_upload.ps1
  src/
    main.py                  # startup + sync do catalogo
    config.py
    catalog/provider.py      # SharePointCatalogProvider (PnP + cache)
    services/
      sharepoint_manager.py
      download_manager.py
      storage.py
      runner.py
    ui/
```

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

copy settings.example.json settings.json
# edite settings.json e preencha catalog.remote_url

python src/main.py
```

## Configurando

1. Em `settings.json`, preencha `catalog.remote_url` com o link SharePoint do
   `catalog.json` (ex.: `.../_layouts/15/download.aspx?UniqueId=...`).
2. Publique no SharePoint o `catalog.json` (formato em `catalog.example.json`).
3. Cada app no JSON deve ter `download_url` e `imagem` como links SharePoint.
4. Ao trocar a arte de um app, incremente `imagem_versao` (ex.: `"1"` → `"2"`)
   para invalidar o cache local sem rebaixar tudo.

Exemplo de app:

```json
{
  "id": "meu-app",
  "nome": "Meu App",
  "descricao": "...",
  "imagem": "https://empresa.sharepoint.com/:i:/r/sites/.../foto.png",
  "imagem_versao": "1",
  "tipo": "exe",
  "download_url": "https://empresa.sharepoint.com/:u:/r/sites/.../app.exe",
  "upload_url": "https://empresa.sharepoint.com/.../AllItems.aspx?id=...",
  "versao": "1.0.0"
}
```

## SharePoint (PnP + PowerShell)

1. No startup, a Suite baixa `catalog.json` via PnP/WebLogin e so baixa imagens
   novas ou com `imagem_versao` alterada.
2. Ao baixar um app (exe/xlsx/xlsm), usa o mesmo fluxo PnP.
3. Upload opcional com `template_sp_upload.ps1` quando houver `upload_url`.

Requisito: PowerShell e modulo `SharePointPnPPowerShellOnline` (CurrentUser).

## Dados locais

```
%LOCALAPPDATA%/SuitePetrobras/
  apps/                    # arquivos baixados dos programas
  catalog/
    catalog.json           # cache do catalogo
    images/                # capas baixadas
    images_manifest.json   # URL + imagem_versao por app (evita redownload)
  installed.json           # manifesto de instalacao
```
