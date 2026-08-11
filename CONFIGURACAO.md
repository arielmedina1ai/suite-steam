# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem informacoes internas.
Textos/cores ficam no `settings.json` local. O **catalogo oficial** (apps, gerencias,
setores, versoes, imagens e links) vive no **SharePoint** e e sincronizado a cada
abertura do programa.

## Modelo

| Publico (versionado) | Local / SharePoint | Para que serve |
| -------------------- | ------------------ | -------------- |
| `settings.example.json` | `settings.json` | Nome/empresa/exe/pasta de dados, textos da home, cores, URL do catalog.json |
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
  "app": {
    "name": "Suite (exemplo)",
    "version": "0.1.0",
    "company": "Nome da Empresa",
    "exe_name": "SuiteAPPs",
    "data_dir": "SuiteApps"
  },
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

- `app.name` / `app.company`: titulo da janela e metadados do `.exe` no pack.
- `app.exe_name`: nome do executavel gerado e prefixo do arquivo de update (`{exe_name}_{versao}.exe`).
- `app.data_dir`: pasta sob `%LOCALAPPDATA%` (padrao `SuiteApps`).
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
  "gerencia_geral": "Geral",
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
`{exe_name}_{versao}.exe` (conforme `app.exe_name`). Ao concluir, a Suite mostra a confirmacao, oculta o
botao de download e abre o Explorer com o arquivo selecionado.

### Gerencias

Cada gerencia lista os `id`s dos apps que ela exibe. O mesmo app pode entrar em
varias gerencias.

Na sidebar, o seletor **GERENCIA** fica acima de **SETORES** (dropdown;
nomes longos usam reticencias e tooltip com o texto completo):
- **Geral** (nada selecionado / `gerencia_geral`): nao filtra — mostra todos os apps.
  O rotulo default e `Geral`; personalize com o campo raiz `gerencia_geral` no `catalog.json`.
- Gerencia escolhida: so os apps listados em `gerencias[].apps`.

A escolha fica em `%LOCALAPPDATA%/<app.data_dir>/preferences.json` e e
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

Capas/icones em `%LOCALAPPDATA%/<app.data_dir>/catalog/images/`, com
`images_manifest.json`. So rebaixam se URL ou `*_versao` mudarem.

### Favoritos

Estrela nos cards e no detalhe. Persistidos em
`%LOCALAPPDATA%/<app.data_dir>/favorites.json`. Se houver ao menos 1 favorito
visivel no filtro atual, o item **Favoritos** aparece na sidebar (apos Inicio).

A cada abertura, a Suite:
1. Baixa o `catalog.json` via PnP/WebLogin (`SharePointPnPPowerShellOnline`).
2. Aplica o filtro de gerencia salvo em `preferences.json` (se houver).
3. Sincroniza capas/icones em lote quando necessario.
4. Em falha de rede/auth, usa o ultimo cache; sem cache, o catalogo local de exemplo.
5. Em falha de dependencia PnP (modulo/DLL), tenta um reparo automatico isolado
   (`scripts/reparar_pnp.ps1`) e um unico retry do download — no maximo um reparo
   por execucao do app, sem reiniciar o programa.

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

Arquivos dos apps: `%LOCALAPPDATA%/<app.data_dir>/apps/<id>/`

---

## 4. Distribuicao como .exe

O **desenvolvedor** edita `settings.json` e gera o pack. O arquivo e embutido no
`.exe`; o usuario final nao precisa editar nem colocar `settings.json` ao lado.

```powershell
# 1. edite settings.json (app.name, company, exe_name, data_dir, ...) e assets/branding/
.\scripts\build_exe.ps1
# 2. distribua dist\{exe_name}.exe
```

| Item | Onde fica |
|------|-----------|
| `{exe_name}.exe` | `dist\` (nome = `app.exe_name`) |
| `settings.json` do build | **Dentro** do bundle (congelado no pack) |
| Assets / scripts PnP | Dentro do bundle |
| Apps, favoritos, cache | `%LOCALAPPDATA%/<app.data_dir>/` |

Override opcional: se existir `settings.json` **ao lado** do `.exe`, ele tem prioridade
sobre o embutido (util para suporte; nao e o fluxo normal).

**Pre-requisitos no PC destino:** Windows PowerShell e o modulo
`SharePointPnPPowerShellOnline` (WebLogin). O `.exe` embute a pasta `scripts/`
(incluindo `reparar_pnp.ps1`), mas **nao** embute o modulo PnP.

- Reparo automatico so ocorre apos falha de dependencia no download.
- Offline no reparo: falha controlada + cache/exemplo.
- PowerShell Gallery necessaria apenas se a reinstalacao for disparada.
- Nunca encerra processos PowerShell externos; cada operacao usa subprocesso isolado.

Reparo manual:

```powershell
powershell .\scripts\reparar_pnp.ps1
```

---

## 5. O que NAO versionar

- `settings.json` (local — nao sobe no Git, mas entra no .exe no momento do build)
- Links/tokens internos no codigo
- Catalogo real ou dados sensiveis no GitHub
- `dist/` / `build/` (artefatos do `flet pack`)
