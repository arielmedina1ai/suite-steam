# SuiteApps

Hub de aplicativos internos no estilo "Steam", desenvolvido em Python + [Flet](https://flet.dev).
Casca configuravel: marca, textos, cores e URL do catalogo vem do `settings.json`
e das imagens em `assets/branding/` — o codigo publico nao amarra a nenhuma empresa.
No menu lateral, um seletor de **gerencia** filtra quais apps do catalogo SharePoint
aparecem; sem selecao, o SuiteApps mostra todos.

> Veja **[CONFIGURACAO.md](CONFIGURACAO.md)**.

## Recursos

- Catalogo sincronizado do SharePoint (PnP) a cada execucao, com cache local.
- Botao **Buscar atualizacoes** na sidebar (mesmo sync da abertura).
- Filtro por **gerencia** na sidebar (persistido em `preferences.json`).
- Home: banner com textos do `settings.sector`; com gerencia selecionada, nome/descricao acima de "Todos os aplicativos".
- Sidebar: Inicio, Favoritos (se houver), seletor de gerencia, setores.
- Sub-setores com descricoes e divisores na tela de cada setor.
- Favoritos locais (estrela) em `%LOCALAPPDATA%/<app.data_dir>/favorites.json`.
- Atualizacao do proprio SuiteApps: o banner aparece no sync; **Baixar Atualizacao** baixa, substitui o `.exe` e relanca (Windows empacotado). Arquivo com o nome padrao do exe, sem sufixo de versao. `settings.json` ao lado e preservado.
- Barra com percentual (ou indeterminado + texto no WebLogin) em download/update/sync.
- Executar nao abre segunda instancia **do mesmo** app ja em execucao (mesmo fora desta sessao). Outros apps do catalogo podem rodar ao mesmo tempo. Com atualizacao pendente, **Atualizar versao** encerra so aquele processo, instala e reabre.
- **Publicar** (sidebar): so aparece se o login Windows estiver em `settings.json` > `publish.users`. Cria/edita apps e envia arquivos ao SharePoint (PnP WebLogin).
- Bandeja no Windows (fechar/minimizar nao encerra) e **iniciar com o Windows** ligado por padrao.
- Branding local em `assets/branding/` (logo, hero, icone da janela e da bandeja).
- Capas/icones em cache por `*_versao`.

## Estrutura

```
suite-steam/
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
  preferences.json         # gerencia selecionada + iniciar com o Windows
  updates/                 # staging da nova versao do proprio SuiteApps
```

Atualizacao (Windows + `.exe`, apos **Baixar Atualizacao**): baixa o objeto com o **nome da URL do catalogo** para `%LOCALAPPDATA%/<data_dir>/updates/`; o helper substitui o exe em uso pelo nome padrao (sem versao) e apaga `updates/`, `*.new.exe` e `*.bak`. Uma segunda abertura do hub reativa a instancia ja em execucao (mutex), inclusive da bandeja.
Fallback (falha ou ambiente sem pack): `%USERPROFILE%\Downloads\{exe_name}.exe`.

## Gerar .exe (Windows)

Empacota com `flet pack` (PyInstaller). Na raiz do repo, com o venv ativo:

```powershell
.\scripts\build_exe.ps1
```

Artefato: `dist\{app.exe_name}.exe` lido do `settings.json` pelo `.\scripts\build_exe.ps1` (`flet pack --name`). Janela e nome no programa: `app.name`. Default so se o campo estiver vazio: `SuiteApps`.

Fluxo do desenvolvedor:

1. Edite `settings.json` (nome, empresa, exe_name, data_dir, URL do catalogo, textos, cores, versao) **antes** do pack.
2. Garanta branding em `assets/branding/` (logo/hero/icone) — entra no bundle.
3. Rode `.\scripts\build_exe.ps1` — o `settings.json` e **embutido** no `.exe`; metadados do Windows (product/company) saem do settings.
4. Distribua so o `.exe`. O usuario final nao precisa editar nem copiar `settings.json`.
5. No PC destino: PowerShell + modulo PnP ainda sao necessarios (o exe nao embute o SharePoint). Login continua `Connect-PnPOnline -UseWebLogin`.

Equivalente manual (substitua pelos valores do seu `settings.json`):

```powershell
# --name e --product-name saem de settings.json (app.exe_name / app.name)
flet pack src\main.py `
  --name <app.exe_name> `
  --product-name "<app.name>" `
  --company-name "<app.company>" `
  --icon assets\branding\window_icon.ico `
  --add-data "assets;assets" `
  --add-data "scripts;scripts" `
  --add-data "settings.json;." `
  --add-data "settings.example.json;." `
  --add-data "catalog.example.json;." `
  --hidden-import pystray `
  --hidden-import pystray._win32 `
  --hidden-import PIL `
  --pyinstaller-build-args=--collect-all=pystray `
  --yes
```
