# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem informacoes internas.
Textos/cores ficam no `settings.json` local. O **catalogo oficial** (apps, versoes,
imagens e links) vive no **SharePoint** e e sincronizado a cada abertura do programa.

## Modelo

| Publico (versionado) | Local / SharePoint | Para que serve |
| -------------------- | ------------------ | -------------- |
| `settings.example.json` | `settings.json` | Nome, textos do setor, cores, **URL do catalog.json** |
| `data/catalog.example.json` | `catalog.json` no SharePoint | Lista real de aplicativos |
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
    "remote_url": "https://empresa.sharepoint.com/.../catalog.json?download=1"
  }
}
```

O unico link sensivel necessario no PC e `catalog.remote_url`.
Use o **link de download direto** do `catalog.json` (com `?download=1` se o SharePoint
oferecer). A Suite baixa esse JSON por HTTP — **sem** PowerShell/PnP.

Os scripts PnP (`scripts/template_sp_*.ps1`) continuam sendo usados so para baixar/enviar
os **aplicativos** (exe/xlsx/xlsm).

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
      "tipo": "xlsm",
      "download_url": "https://empresa.sharepoint.com/:x:/r/sites/.../arquivo.xlsm",
      "upload_url": "https://empresa.sharepoint.com/.../AllItems.aspx?id=...",
      "versao": "1.2.0"
    }
  ]
}
```

Campos:
- `download_url`: link do arquivo (PnP baixa ao clicar em Baixar/Instalar).
- `imagem`: link SharePoint da imagem (baixada no startup para cache local).
- `upload_url` (opcional): pasta de envio — habilita "Enviar para SharePoint".
- `tipo`: `exe`, `xlsx` ou `xlsm`.

A cada abertura, a Suite:
1. Baixa o `catalog.json` pelo link de download direto (HTTP).
2. Baixa as imagens dos apps (tambem por download direto, se forem URLs).
3. Guarda cache em `%LOCALAPPDATA%/SuitePetrobras/catalog/`.
4. Se a sincronizacao falhar, usa o ultimo cache.

---

## 3. Acoes na tela do aplicativo

- **Baixar / Instalar** ou **Executar**
- **Baixar novamente / Atualizar versao** (quando ja instalado)
- **Enviar para SharePoint** (se houver `upload_url`)
- **Desinstalar** (remove arquivos locais e o registro)

Arquivos dos apps: `%LOCALAPPDATA%/SuitePetrobras/apps/<id>/`

---

## Resumo da privacidade

- Repo publico = codigo + exemplos + este guia.
- No PC: `settings.json` (textos + URL do catalogo).
- No SharePoint: catalogo, imagens e arquivos dos programas.
- Nada disso volta ao repositorio publico.
