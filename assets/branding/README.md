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
(`logo.png`, `window_icon.png`) ficam no `.gitignore` e nao voltam ao repo publico.

| Arquivo de producao | Exemplo versionado | Uso | Resolucao |
|---------------------|--------------------|-----|-----------|
| `logo.png` | `logo.example.png` | Emblema (antigo "SP") | **512 x 512** (min. 256) |
| `window_icon.png` | `window_icon.example.png` | Icone da janela / tarefa | **256 x 256** |

Formato: PNG, proporcao 1:1, transparencia ok. DPI: 72 (ou ignore — pixels importam).

Se `logo.png` / `window_icon.png` nao existirem, a Suite usa fallback (texto "SP" / icone padrao).
