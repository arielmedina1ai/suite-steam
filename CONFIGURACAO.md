# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem informacoes internas.
Textos/cores ficam no `settings.json` local. O **catalogo oficial** (apps, versoes,
imagens e links) vive no **SharePoint** e e sincronizado a cada abertura do programa.

## Modelo

| Publico (versionado) | Local / SharePoint | Para que serve |
| -------------------- | ------------------ | -------------- |
| `settings.example.json` | `settings.json` | Nome, textos do setor, cores, **URL do catalog.json** |
| `catalog.example.json` | `catalog.json` no SharePoint | Lista real de aplicativos |
| `assets/branding/*.example.png` | `logo.png` / `hero.png` / `window_icon.png` | Logo sidebar, banner home, icone janela |
| `scripts/*.ps1` | (fixos) | Download/upload via PnP |

## Passo a passo

1. Copie `settings.example.json` para `settings.json`.
2. Edite textos/cores e preencha `catalog.remote_url` com o link SharePoint do `catalog.json`.
3. Publique no SharePoint um `catalog.json` no formato do exemplo (com links reais).
4. Publique as imagens no SharePoint e use os links no campo `imagem` de cada app.
5. Rode `python src/main.py` — a Suite sincroniza o catalogo (pode abrir WebLogin).

---

## 1. settings.json (local)

```json
{
  "app": { "name": "Suite Petrobras", "version": "0.1.0" },
  "sector": {
    "name": "Nome do setor",
    "tagline": "Frase de efeito",
    "description": "Apresentacao..."
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

O unico link sensivel necessario no PC e `catalog.remote_url`.
Cole o link do SharePoint **sem alterar**, tipicamente:

`https://.../teams/.../_layouts/15/download.aspx?UniqueId=...`

Esse link exige autenticacao (HTTP 401 sem login). Por isso a Suite baixa o catalogo
via **PnP + WebLogin** (mesma solucao dos apps), nao por HTTP puro.

Os scripts PnP tambem baixam/enviam os aplicativos (exe/xlsx/xlsm).

---

## 2. catalog.json no SharePoint

Hospede este arquivo no SharePoint (e cole o link em `catalog.remote_url`):

```json
{
  "apps": [
    {
      "id": "relatorio-producao",
      "nome": "Relatorio de Producao",
      "descricao": "Descricao do app...",
      "imagem": "https://empresa.sharepoint.com/:i:/r/sites/.../relatorio.png",
      "imagem_versao": "1",
      "icone": "https://empresa.sharepoint.com/:i:/r/sites/.../relatorio-icon.png",
      "icone_versao": "1",
      "tipo": "xlsm",
      "download_url": "https://empresa.sharepoint.com/:x:/r/sites/.../arquivo.xlsm",
      "upload_url": "https://empresa.sharepoint.com/.../AllItems.aspx?id=...",
      "versao": "1.2.0"
    }
  ]
}
```

### Imagens e cache

Cada app aponta `imagem` (capa) e opcionalmente `icone` para links SharePoint.
Na primeira sync a Suite baixa e grava em `%LOCALAPPDATA%/SuitePetrobras/catalog/images/`,
com `images_manifest.json` guardando URL + versao por midia.

Nas proximas aberturas, se URL e `*_versao` forem iguais e o arquivo existir,
**nao ha novo download**. Ao trocar a arte, incremente `imagem_versao` ou
`icone_versao` (ex.: `"1"` → `"2"`).

Se `imagem` ou `icone` forem `""`, a Suite usa placeholder (badge / icone por tipo).

Campos:
- `download_url`: link do arquivo (PnP baixa ao clicar em Baixar/Instalar).
- `imagem`: link SharePoint da **capa** (tela de detalhe; cacheada localmente).
- `imagem_versao`: bump ao trocar a capa.
- `icone`: link SharePoint do **icone** (sidebar / cards; cacheado localmente).
- `icone_versao`: bump ao trocar o icone.
- `versao`: bump ao publicar arquivo novo do app (mostra **Atualizar versao** nos PCs).
- `upload_url` (opcional): pasta de envio — habilita "Enviar para SharePoint".
- `tipo`: `exe`, `xlsx` ou `xlsm`.

A cada abertura, a Suite:
1. Baixa o `catalog.json` via PnP/WebLogin (aceita `download.aspx?UniqueId=...`).
2. Para capas/icones: usa cache se `url` + `*_versao` baterem; o que falta
   baixa em **lote** (um WebLogin por site).
3. Guarda cache em `%LOCALAPPDATA%/SuitePetrobras/catalog/`.
4. Se a sincronizacao falhar, usa o ultimo cache.

---

## 2.1 Branding local (nao vai no SharePoint)

Imagens da casca ficam em `assets/branding/`. Copie os exemplos e troque pela arte real:

```text
copy assets\branding\logo.example.png assets\branding\logo.png
copy assets\branding\hero.example.png assets\branding\hero.png
copy assets\branding\window_icon.example.png assets\branding\window_icon.png
```

| Arquivo (producao) | Exemplo | Onde aparece | Resolucao |
|--------------------|---------|--------------|-----------|
| `logo.png` | `logo.example.png` | Emblema da **sidebar** | **512 x 512** px (1:1) |
| `hero.png` | `hero.example.png` | Banner da **tela inicial** | **2220 x 1140** px |
| `window_icon.png` | `window_icon.example.png` | Icone da janela (gera `.ico`) | **256 x 256** px |

DPI: 72. Proporcao do hero: **2220:1140** (~1,95:1). Na tela ele aparece
com ~860 px de largura; 2220x1140 cobre bem HiDPI (2x).

**Nota Windows:** o icone da janela exige `.ico`. A Suite converte
`window_icon.png` → `window_icon.ico` automaticamente ao abrir.

Capas de aplicativo (campo `imagem`) continuam no SharePoint — recomendado
**1040 x 600** (16:9) ou similar. Icones de app (campo `icone`): **256 x 256** px.

---

## 3. Acoes na tela do aplicativo

- **Baixar / Instalar** ou **Executar**
- **Atualizar versao** (aparece so quando `versao` do catalogo difere da instalada; rebaixa o arquivo)
- **Enviar para SharePoint** (se houver `upload_url`)
- **Desinstalar** (remove arquivos locais e o registro)

Arquivos dos apps: `%LOCALAPPDATA%/SuitePetrobras/apps/<id>/`

---

## Resumo da privacidade

- Repo publico = codigo + exemplos + este guia.
- No PC: `settings.json` (textos + URL do catalogo).
- No SharePoint: catalogo, imagens e arquivos dos programas.
- Nada disso volta ao repositorio publico.
