# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem informacoes internas.
Textos/cores ficam no `settings.json` local. O **catalogo oficial** (apps, gerencias,
setores, versoes, imagens e links) vive no **SharePoint** e e sincronizado a cada
abertura do programa.

## Modelo

| Publico (versionado) | Local / SharePoint | Para que serve |
| -------------------- | ------------------ | -------------- |
| `settings.example.json` | `settings.json` | Nome/versao da Suite, textos da home, cores, URL do catalog.json |
| `catalog.example.json` | `catalog.json` no SharePoint | Suite update, gerencias, setores, apps |
| `assets/branding/*.example.png` | `logo.png` / `hero.png` / `window_icon.png` | Logo sidebar, banner home, icone janela |
| `scripts/*.ps1` | (fixos) | Download/upload via PnP |

## Passo a passo

1. Copie `settings.example.json` para `settings.json`.
2. Edite textos do setor (home), cores e `catalog.remote_url`.
3. Publique no SharePoint um `catalog.json` no formato do exemplo (com links reais).
4. Publique as imagens no SharePoint e use os links nos campos `imagem` / `icone`.
5. Rode `python src/main.py` — a Suite sincroniza o catalogo (pode abrir WebLogin).

---

## 1. settings.json (local)

```json
{
  "app": { "name": "Suite Petrobras", "version": "0.1.0" },
  "sector": {
    "name": "Nome do setor",
    "tagline": "Frase de efeito",
    "description": "Apresentacao no banner da tela Inicio..."
  },
  "theme": {
    "primary": "#008542",
    "primary_dark": "#00522A",
    "accent": "#FFD000",
    "bg": "#0E1512",
    "surface": "#16211C",
    "text": "#EAF3EE"
  },
  "catalog": {
    "remote_url": "https://empresa.sharepoint.com/teams/.../_layouts/15/download.aspx?UniqueId=..."
  }
}
```

- `app.version`: versao instalada desta Suite (comparada com `suite.versao` do catalogo).
- `sector.*`: titulo, tagline e descricao do **banner** na tela Inicio (sempre no mesmo lugar).

O unico link sensivel necessario no PC e `catalog.remote_url` (PnP + WebLogin).

---

## 2. catalog.json no SharePoint

Estrutura completa (veja `catalog.example.json`):

```json
{
  "suite": {
    "versao": "0.2.0",
    "download_url": "https://empresa.sharepoint.com/.../SuiteAPPs.exe"
  },
  "gerencias": [
    {
      "id": "gerencia-1",
      "nome": "Gerencia 1",
      "descricao": "Texto exibido no Inicio (acima de Todos os aplicativos).",
      "apps": ["relatorio-producao", "monitor-ativos"]
    }
  ],
  "setores": [
    {
      "id": "setor-1",
      "nome": "Setor 1",
      "descricao": "Descricao do setor.",
      "sub_setores": [
        { "id": "sub-a", "nome": "Sub-setor A", "descricao": "..." }
      ]
    }
  ],
  "apps": [
    {
      "id": "relatorio-producao",
      "nome": "Relatorio de Producao",
      "descricao": "Descricao do app...",
      "setor": "setor-1",
      "sub_setor": "sub-a",
      "imagem": "https://...",
      "imagem_versao": "1",
      "icone": "https://...",
      "icone_versao": "1",
      "tipo": "xlsm",
      "download_url": "https://...",
      "versao": "1.2.0"
    }
  ]
}
```

### Suite (atualizacao)

Se `suite.versao` for diferente de `settings.app.version` e houver `download_url`,
a sidebar mostra **Baixar atualizacao**. O download usa o **link exato** do catalogo;
ao salvar, o arquivo vai para a pasta **Downloads** do Windows como
`SuiteAPPs_{versao}.exe`. Ao concluir, a Suite mostra a confirmacao, oculta o
botao de download e abre o Explorer com o arquivo selecionado.

### Gerencias

Cada gerencia lista os `id`s dos apps que ela exibe. O mesmo app pode entrar em
varias gerencias.

Na sidebar, o seletor **GERENCIA** fica acima de **SETORES**:
- **Todas** (nada selecionado): nao filtra — mostra todos os apps.
- Gerencia escolhida: so os apps listados em `gerencias[].apps`.

A escolha fica em `%LOCALAPPDATA%/SuitePetrobras/preferences.json` e e
restaurada na proxima abertura.

Com gerencia selecionada, o **Inicio** mostra nome + descricao da gerencia
**acima** do topico "Todos os aplicativos" (o banner continua com `settings.sector`).

### Setores e sub-setores

- `setores[]`: id, nome, descricao e lista de `sub_setores`.
- Cada app aponta `setor` e `sub_setor` por **id**.
- Sidebar lista setores (com pelo menos 1 app visivel) na ordem do JSON.
- Dentro do setor, apps sao agrupados por sub-setor (com divisor e descricao).

### Campos do app

- `download_url`: link do arquivo (PnP).
- `setor` / `sub_setor`: ids no bloco `setores`.
- `imagem` / `imagem_versao`: capa (detalhe).
- `icone` / `icone_versao`: icone nos cards.
- `versao`: bump ao publicar arquivo novo do app.
- `upload_url` (opcional): habilita envio ao SharePoint.
- `tipo`: `exe`, `xlsx` ou `xlsm`.

### Imagens e cache

Capas/icones em `%LOCALAPPDATA%/SuitePetrobras/catalog/images/`, com
`images_manifest.json`. So rebaixam se URL ou `*_versao` mudarem.

### Favoritos

Estrela nos cards e no detalhe. Persistidos em
`%LOCALAPPDATA%/SuitePetrobras/favorites.json`. Se houver ao menos 1 favorito
visivel no filtro atual, o item **Favoritos** aparece na sidebar (apos Inicio).

A cada abertura, a Suite:
1. Baixa o `catalog.json` via PnP/WebLogin.
2. Aplica o filtro de gerencia salvo em `preferences.json` (se houver).
3. Sincroniza capas/icones em lote quando necessario.
4. Em falha, usa o ultimo cache.

---

## 2.1 Branding local (nao vai no SharePoint)

```text
copy assets\branding\logo.example.png assets\branding\logo.png
copy assets\branding\hero.example.png assets\branding\hero.png
copy assets\branding\window_icon.example.png assets\branding\window_icon.png
```

| Arquivo (producao) | Exemplo | Onde aparece | Resolucao |
|--------------------|---------|--------------|-----------|
| `logo.png` | `logo.example.png` | Emblema da **sidebar** | **512 x 512** px (1:1) |
| `hero.png` | `hero.example.png` | Banner da **tela inicial** | **480 x 246** px (ideal; proporcao 2220:1140) |
| `window_icon.png` | `window_icon.example.png` | Icone da janela (gera `.ico`) | **256 x 256** px |

**Nota Windows:** a Suite converte `window_icon.png` → `window_icon.ico` ao abrir.

---

## 3. Acoes na tela do aplicativo

- **Favoritar** (estrela)
- **Baixar / Instalar** ou **Executar**
- **Atualizar versao** (quando `versao` do catalogo difere da instalada)
- **Enviar para SharePoint** (se houver `upload_url`)
- **Desinstalar**

Arquivos dos apps: `%LOCALAPPDATA%/SuitePetrobras/apps/<id>/`

---

## 4. Distribuicao como .exe

Gere o executavel na maquina de build:

```powershell
.\scripts\build_exe.ps1
```

| Item | Onde fica |
|------|-----------|
| `SuiteAPPs.exe` | `dist\` (apos o pack) |
| `settings.json` (editavel) | **Ao lado do .exe** |
| Assets / scripts PnP | Dentro do bundle (somente leitura) |
| Apps, favoritos, cache | `%LOCALAPPDATA%/SuitePetrobras/` (inalterado) |

**Por que o `settings.json` nao vai “dentro” do .exe?** O bundle PyInstaller e so-leitura.
La estao o `catalog.remote_url`, textos do setor e cores — coisas que mudam por instalacao
sem recompilar. Por isso o arquivo fica ao lado do exe (ou em
`%LOCALAPPDATA%/SuitePetrobras/settings.json`). O pack embute so o
`settings.example.json` como fallback de placeholders.

**Pre-requisitos no PC destino:** PowerShell e modulo PnP.PowerShell (WebLogin). O `.exe` nao substitui essa dependencia.

---

## 5. O que NAO versionar

- `settings.json` (local)
- Links/tokens internos no codigo
- Catalogo real ou dados sensiveis no GitHub
- `dist/` / `build/` (artefatos do `flet pack`)
