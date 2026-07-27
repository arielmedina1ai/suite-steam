# Branding da Suite (assets locais)

Estas imagens ficam **no software** (pasta `assets/branding/`), nao no SharePoint.

## Como configurar (mesmo padrao do settings)

```text
copy logo.example.png logo.png
copy hero.example.png hero.png
copy window_icon.example.png window_icon.png
```

Substitua pelos arquivos reais do setor. Os `*.example.*` sao versionados; os de
producao ficam no `.gitignore`.

| Arquivo de producao | Exemplo | Uso | Resolucao recomendada |
|---------------------|---------|-----|------------------------|
| `logo.png` | `logo.example.png` | Emblema da **sidebar** (antigo "SP") | **512 x 512** (min. 256), 1:1 |
| `hero.png` | `hero.example.png` | Banner da **tela inicial** (centro) | **2220 x 1140** (proporcao ~1,95:1) |
| `window_icon.png` | `window_icon.example.png` | Base do icone da janela | **256 x 256**, 1:1 |

DPI: 72 (padrao de tela). O que importa e o tamanho em **pixels**.

### Banner da home (`hero.png`)

Proporcao fixa **2220 : 1140**. Na UI a Suite exibe em ~860 px de largura
(altura ~442 px). Por isso **2220 x 1140** e o ponto ideal (cerca de 2x a
exibicao, nitido em monitores HiDPI). Pode usar metade (**1110 x 570**) se
quiser arquivo menor; evite subir muito alem de 2220 (peso sem ganho visual).

O `hero.example.png` do repo esta em **1110 x 570** (mesma proporcao, placeholder leve).

### Icone da janela (Windows / Flet)

O Flet no Windows exige `.ico` com caminho absoluto. A Suite converte
`window_icon.png` → `window_icon.ico` automaticamente.

Sem `logo.png` / `hero.png` / `window_icon.png`, a Suite usa fallbacks.
