# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem informacoes internas.
Textos/cores ficam no `settings.json` local. O **catalogo oficial** (apps, versoes,
imagens e links) vive no **SharePoint** e e sincronizado a cada abertura do programa.

## Modelo

| Publico (versionado) | Local / SharePoint | Para que serve |
| -------------------- | ------------------ | -------------- |
| `settings.example.json` | `settings.json` | Nome, textos do setor, cores, **URL do catalog.json** |
| `catalog.example.json` | `catalog.json` no SharePoint | Lista real de aplicativos |
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
      "tipo": "xlsm",
      "download_url": "https://empresa.sharepoint.com/:x:/r/sites/.../arquivo.xlsm",
      "upload_url": "https://empresa.sharepoint.com/.../AllItems.aspx?id=...",
      "versao": "1.2.0"
    }
  ]
}
```

### Imagens e cache

Cada app aponta `imagem` para um link SharePoint. Na primeira sync a Suite baixa
a capa e grava em `%LOCALAPPDATA%/SuitePetrobras/catalog/images/`, com um
`images_manifest.json` que guarda `url` + `imagem_versao` por app.

Nas proximas aberturas, se a URL e a `imagem_versao` forem as mesmas e o arquivo
ainda existir localmente, **nao ha nova consulta/download ao SharePoint** para
aquela imagem. Ao trocar a arte no SharePoint, incremente `imagem_versao`
(ex.: `"1"` → `"2"`) — isso invalida so aquele app, sem rebaixar as demais capas.

Isso e mais barato e previsivel do que consultar metadados (ETag/TimeLastModified)
de dezenas de arquivos no SharePoint a cada startup.

Campos:
- `download_url`: link do arquivo (PnP baixa ao clicar em Baixar/Instalar).
- `imagem`: link SharePoint da imagem (cacheada localmente).
- `imagem_versao`: bump ao trocar a arte (invalida so aquele cache).
- `versao`: bump ao publicar arquivo novo do app (mostra **Atualizar versao** nos PCs).
- `upload_url` (opcional): pasta de envio — habilita "Enviar para SharePoint".
- `tipo`: `exe`, `xlsx` ou `xlsm`.

A cada abertura, a Suite:
1. Baixa o `catalog.json` via PnP/WebLogin (aceita `download.aspx?UniqueId=...`).
2. Para cada imagem: usa cache se `url` + `imagem_versao` baterem; senao baixa via PnP.
3. Guarda cache em `%LOCALAPPDATA%/SuitePetrobras/catalog/`.
4. Se a sincronizacao falhar, usa o ultimo cache.

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
