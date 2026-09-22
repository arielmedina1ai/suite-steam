# Guia de Configuracao do SuiteApps

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
5. Rode `python src/main.py` — o SuiteApps sincroniza o catalogo (pode abrir WebLogin).

---

## 1. settings.json (local)

```json
{
  "app": {
    "name": "SuiteApps",
    "version": "0.1.0",
    "company": "Nome da Empresa",
    "exe_name": "SuiteApps",
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

- `app.name`: **titulo da janela**, nome na sidebar e `--product-name` no pack. Default se vazio: SuiteApps. Vale o texto do `settings.json` (ex.: `SuiteAPPs`).
- `app.exe_name`: **arquivo** gerado (`dist\{exe_name}.exe`), `flet pack --name`, atalho de inicio e staging de update. Default se vazio: SuiteApps. O `.\scripts\build_exe.ps1` le este campo do `settings.json` e imprime o valor usado.
- `app.company`: metadado do `.exe` no pack (`--company-name`), se preenchido.
- `app.data_dir`: pasta sob `%LOCALAPPDATA%` (padrao `SuiteApps`).
- `app.version`: versao instalada (comparada com `suite.versao` do catalogo).
- `sector.*`: titulo, tagline e descricao do **banner** na tela Inicio (sempre no mesmo lugar).

O unico link sensivel necessario no PC e `catalog.remote_url` (PnP + WebLogin).

---

## 2. catalog.json no SharePoint

Estrutura completa (veja `catalog.example.json`):

```json
{
  "suite": {
    "versao": "0.2.0",
    "download_url": "https://empresa.sharepoint.com/.../SuiteApps.exe"
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

### SuiteApps (atualizacao)

Se `suite.versao` for diferente de `settings.app.version` e houver `download_url`,
a sidebar mostra **Baixar Atualizacao**. O download **nao** comeca sozinho (nem no
sync da abertura nem em **Buscar atualizacoes**).

Depois do clique, no Windows empacotado, o download usa o **nome do arquivo no
link do catalogo** (ex. `SuiteAPPs.exe` / UniqueId) e grava so em
`%LOCALAPPDATA%/<app.data_dir>/updates/`. Nao procura `*.new.exe` no SharePoint
e nao deixa extras ao lado do `.exe`. Um helper substitui o binario em uso pelo
nome padrao (`app.exe_name` / nome em execucao, **sem** sufixo de versao),
relanca, e apaga `updates/`, `*.new.exe`, `*.bak` e `*.old`. Um `settings.json`
ao lado do executavel, se existir, nao e apagado.

Uma segunda abertura do hub (clique impaciente) nao inicia outro processo: o
mutex nomeado reativa a janela ja aberta, inclusive se estiver na bandeja.

Enquanto baixa, a sidebar (e a home) mostram barra com percentual; no WebLogin a
barra fica indeterminada ate haver progresso mensuravel.

Se o download ou a troca falhar, aparece mensagem curta e o botao **Baixar Atualizacao**
permanece como fallback. O app atual continua usavel.

O botao **Buscar atualizacoes** na sidebar dispara o mesmo sync do SharePoint da
abertura (catalogo, badges de versao e banner do proprio SuiteApps).

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

A cada abertura, o SuiteApps:
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

**Nota Windows:** o SuiteApps converte `window_icon.png` → `window_icon.ico` ao abrir.
O mesmo icone e usado na bandeja. Fechar ou minimizar envia o app para a area de
notificacao (Abrir / Sair). **Iniciar com o Windows** vem ligado por padrao
(atalho na pasta Startup); da para desligar no interruptor da sidebar
(`preferences.json` > `start_with_windows`).

---

## 3. Acoes na tela do aplicativo

- **Favoritar** (estrela)
- **Baixar / Instalar** ou **Executar** (nao abre segunda instancia **do mesmo** app
  se ele ja estiver em execucao, inclusive iniciado antes do hub / pelo Startup;
  outros apps do catalogo podem ficar abertos ao mesmo tempo)
- **Atualizar versao** (quando `versao` do catalogo difere da instalada; se **esse**
  processo estiver aberto, o hub encerra, instala e reabre)
- Barra de progresso com percentual durante download/update (indeterminado no WebLogin)
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

**Pre-requisitos no PC destino:** PowerShell e modulo SharePointPnPPowerShellOnline (WebLogin). O `.exe` nao substitui essa dependencia e nao embute o PnP.

---

## 5. O que NAO versionar

- `settings.json` (local — nao sobe no Git, mas entra no .exe no momento do build)
- Links/tokens internos no codigo
- Catalogo real ou dados sensiveis no GitHub
- `dist/` / `build/` (artefatos do `flet pack`)
