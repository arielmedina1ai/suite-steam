# Suite

Hub de aplicativos internos no estilo "Steam", desenvolvido em Python + [Flet](https://flet.dev).
Casca configuravel: marca, textos, cores e URL do catalogo vem do `settings.json`
e das imagens em `assets/branding/` — o codigo publico nao amarra a nenhuma empresa.
No menu lateral, um seletor de **gerencia** filtra quais apps do catalogo SharePoint
aparecem; sem selecao, a Suite mostra todos.

> Veja **[CONFIGURACAO.md](CONFIGURACAO.md)**.

## Dependencias SharePoint (PnP)

A Suite usa **exclusivamente** o modulo `SharePointPnPPowerShellOnline` com
`Connect-PnPOnline -UseWebLogin`. O `.exe` nao embute o modulo.

- Downloads rodam em subprocessos PowerShell isolados (nao encerra PowerShells externos).
- Se o download falhar por dependencia (modulo/DLL/assembly), a Suite tenta **um**
  reparo automatico via `scripts/reparar_pnp.ps1` e **um** novo download
  (no maximo um reparo por execucao do app).
- Sem internet no momento do reparo, a falha e controlada: usa cache local ou o
  catalogo de exemplo (`catalog.example.json`).
- Reinstalacao usa escopo `CurrentUser` (PowerShell Gallery); nao pede elevacao silenciosa.

Reparo manual:

```powershell
powershell .\scripts\reparar_pnp.ps1
```

## Recursos

- Catalogo sincronizado do SharePoint (PnP) a cada execucao, com cache local.
- Filtro por **gerencia** na sidebar (persistido em `preferences.json`).
- Home: banner com textos do `settings.sector`; com gerencia selecionada, nome/descricao acima de "Todos os aplicativos".
- Sidebar: Inicio, Favoritos (se houver), seletor de gerencia, setores.
- Sub-setores com descricoes e divisores na tela de cada setor.
- Favoritos locais (estrela) em `%LOCALAPPDATA%/<app.data_dir>/favorites.json`.
- Atualizacao da Suite: download pelo link do catalogo; salva como `{exe_name}_{versao}.exe` em Downloads.
- Branding local em `assets/branding/` (logo, hero, icone da janela).
- Capas/icones em cache por `*_versao`.

## Estrutura

```
Suite-steam/
  settings.example.json      # modelo (copie p/ settings.json)
  catalog.example.json       # modelo do catalogo para publicar no SharePoint
  assets/branding/           # logo, hero e icone da janela (locais)
  CONFIGURACAO.md
  scripts/
  src/
    main.py
    config.py
    catalog/provider.py
    models.py
    services/
    ui/
```

## Como rodar

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

copy settings.example.json settings.json
# edite: app (name, company, exe_name, data_dir), sector, catalog.remote_url

python src/main.py
```

Para gerar o `.exe`, apos o `pip install` (inclui `pyinstaller` e `flet-cli`):

```powershell
.\scripts\build_exe.ps1
```

Veja a secao **Gerar .exe** abaixo.

## Configurando

1. Em `settings.json`, defina `app` (nome, empresa, exe, pasta de dados), textos do `sector`, cores e `catalog.remote_url`.
2. Publique no SharePoint o `catalog.json` (formato em `catalog.example.json`).
3. No catalogo: `suite`, `gerencias`, `setores` (com `sub_setores`) e `apps`.
4. Apps referenciam `setor` / `sub_setor` por **id**; entram nas gerencias via `gerencias[].apps`.
5. Copie `assets/branding/*.example.png` para os nomes de producao.

## Dados locais

Pasta sob `%LOCALAPPDATA%` definida por `app.data_dir` (padrao `SuiteApps`):

```
%LOCALAPPDATA%/SuiteApps/
  apps/                    # arquivos baixados dos programas
  catalog/
    catalog.json           # cache do catalogo
    images/                # capas e icones
    images_manifest.json
  installed.json           # manifesto de instalacao
  favorites.json           # favoritos do usuario
  preferences.json         # gerencia selecionada (filtro)
```

Update da Suite (quando disponivel): `%USERPROFILE%\Downloads\{exe_name}_{versao}.exe`

## Gerar .exe (Windows)

Empacota com `flet pack` (PyInstaller). Na raiz do repo, com o venv ativo:

```powershell
.\scripts\build_exe.ps1
```

Artefato: `dist\{exe_name}.exe` conforme `app.exe_name` no settings (nao versionado; `dist/` e `build/` no `.gitignore`).

Fluxo do desenvolvedor:

1. Edite `settings.json` (nome, empresa, exe_name, data_dir, URL do catalogo, textos, cores, versao) **antes** do pack.
2. Garanta branding em `assets/branding/` (logo/hero/icone) — entra no bundle.
3. Rode `.\scripts\build_exe.ps1` — o `settings.json` e **embutido** no `.exe`; metadados do Windows (product/company) saem do settings.
4. Distribua so o `.exe`. O usuario final nao precisa editar nem copiar `settings.json`.
5. No PC destino: PowerShell + modulo PnP ainda sao necessarios (o exe nao embute o SharePoint).

Equivalente manual (substitua pelos valores do seu `settings.json`):

```powershell
flet pack src\main.py `
  --name SuiteAPPs `
  --product-name "Suite (exemplo)" `
  --company-name "Nome da Empresa" `
  --icon assets\branding\window_icon.ico `
  --add-data "assets;assets" `
  --add-data "scripts;scripts" `
  --add-data "settings.json;." `
  --add-data "settings.example.json;." `
  --add-data "catalog.example.json;." `
  --yes
```
