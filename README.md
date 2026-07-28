# Suite Petrobras

Hub de aplicativos internos no estilo "Steam", desenvolvido em Python + [Flet](https://flet.dev).
A Suite e instalada **por gerencia**: cada PC aponta um id de gerencia no `settings.json`
e so ve os apps atribuidos a ela no catalogo SharePoint.

> **Casca configuravel:** repositorio publico sem dados internos. Veja **[CONFIGURACAO.md](CONFIGURACAO.md)**.

## Recursos

- Catalogo sincronizado do SharePoint (PnP) a cada execucao, com cache local.
- Filtragem por **gerencia** (`settings.gerencia` + `catalog.gerencias`).
- Sidebar: Inicio, Favoritos (se houver), setores; home com descricao da gerencia.
- Sub-setores com descricoes e divisores na tela de cada setor.
- Favoritos locais (estrela) em `%LOCALAPPDATA%/SuitePetrobras/favorites.json`.
- Atualizacao da Suite (`catalog.suite`) → Download como `SuiteAPPs_VERSAO.exe`.
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

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

copy settings.example.json settings.json
# edite: gerencia, catalog.remote_url, app.version

python src/main.py
```

## Configurando

1. Em `settings.json`, defina `gerencia` (ex.: `"gerencia-1"`) e `catalog.remote_url`.
2. Publique no SharePoint o `catalog.json` (formato em `catalog.example.json`).
3. No catalogo: `suite`, `gerencias`, `setores` (com `sub_setores`) e `apps`.
4. Apps referenciam `setor` / `sub_setor` por **id**; entram nas gerencias via `gerencias[].apps`.
5. Copie `assets/branding/*.example.png` para os nomes de producao.

## Dados locais

```
%LOCALAPPDATA%/SuitePetrobras/
  apps/                    # arquivos baixados dos programas
  catalog/
    catalog.json           # cache do catalogo
    images/                # capas e icones
    images_manifest.json
  installed.json           # manifesto de instalacao
  favorites.json           # favoritos do usuario
```

Update da Suite (quando disponivel): `%USERPROFILE%\Downloads\SuiteAPPs_{versao}.exe`
