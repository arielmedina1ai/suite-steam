# Branding da Suite (assets locais)

Estas imagens ficam **no software** (pasta `assets/branding/`), nao no SharePoint.

## Como configurar (mesmo padrao do settings)

1. Copie os exemplos para os nomes de producao:

```text
copy logo.example.png logo.png
copy window_icon.example.png window_icon.png
```

2. Substitua `logo.png` e `window_icon.png` pelas artes reais do setor.

Os `*.example.png` sao placeholders versionados. Os arquivos sem `.example`
ficam no `.gitignore` e nao voltam ao repo publico.

| Arquivo de producao | Exemplo versionado | Uso | Resolucao |
|---------------------|--------------------|-----|-----------|
| `logo.png` | `logo.example.png` | Emblema (antigo "SP") | **512 x 512** (min. 256) |
| `window_icon.png` | `window_icon.example.png` | Base do icone da janela | **256 x 256** |

Formato: PNG, proporcao 1:1, transparencia ok. DPI: 72 (ou ignore — pixels importam).

### Icone da janela (Windows / Flet)

No Windows o Flet **so aceita `.ico` com caminho absoluto**. A Suite faz isso
automaticamente: se existir `window_icon.png`, gera `window_icon.ico` ao lado
na primeira execucao. Voce tambem pode colocar um `window_icon.ico` pronto.

Se `logo.png` / `window_icon.png` nao existirem, a Suite usa fallback (texto "SP" / icone padrao do Flet).
