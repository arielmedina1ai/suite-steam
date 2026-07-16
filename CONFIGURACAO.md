# Guia de Configuracao da Suite

Este repositorio e uma **casca publica**: o codigo nao contem nenhuma informacao interna.
Todos os textos, cores, aplicativos, links e imagens sao definidos em **arquivos locais que
NAO sao versionados** (nao voltam para o repositorio publico).

## Modelo: arquivos de exemplo -> arquivos locais

| Publico (versionado, no repo) | Local (voce cria, NAO versionado) | Para que serve                         |
| ----------------------------- | --------------------------------- | -------------------------------------- |
| `settings.example.json`       | `settings.json`                   | Nome do app, textos do setor, cores    |
| `data/catalog.example.json`   | `data/catalog.json`               | Lista de aplicativos e links           |
| `assets/images/README.md`     | `assets/images/*.png`             | Imagens de cada aplicativo             |

Regra do carregamento: se o arquivo **local** existir, ele e usado; senao, cai no
`*.example`. Ou seja, apos clonar, o programa ja roda com os placeholders.

## Passo a passo (primeira configuracao)

1. Copie `settings.example.json` para `settings.json`.
2. Copie `data/catalog.example.json` para `data/catalog.json`.
3. Edite os dois arquivos com as informacoes reais (veja secoes abaixo).
4. Coloque as imagens em `assets/images/`.
5. Rode `python src/main.py`.

Nada do que voce editar nesses arquivos locais vai para o repositorio publico
(estao no `.gitignore`).

---

## 1. Textos do setor, nome e cores -> `settings.json`

```json
{
  "app": {
    "name": "Suite Petrobras",        // titulo da janela e do cabecalho lateral
    "version": "0.1.0"                 // versao exibida abaixo do titulo
  },
  "sector": {
    "name": "Nome do seu setor",       // titulo grande na tela inicial
    "tagline": "Frase de efeito",      // subtitulo em destaque (amarelo)
    "description": "Texto de apresentacao do setor..."  // paragrafo da tela inicial
  },
  "theme": {
    "primary": "#008542",              // verde principal (botoes, item selecionado)
    "primary_dark": "#00522A",         // verde escuro (gradiente do banner)
    "accent": "#FFD000",               // amarelo (destaques/icones)
    "bg": "#0E1512",                   // cor de fundo da janela
    "surface": "#16211C",              // cor dos cards/menu lateral
    "text": "#EAF3EE"                  // cor do texto
  },
  "catalog": {
    "local_file": "data/catalog.json", // de onde ler o catalogo local
    "remote_url": null                 // opcional: URL de um catalog.json remoto (SharePoint)
  }
}
```

> Observacao: JSON nao aceita comentarios `//`. Eles estao aqui apenas para explicacao;
> no arquivo real remova-os.

Onde cada campo aparece na tela:
- `app.name` / `app.version`: cabecalho do menu lateral e titulo da janela.
- `sector.name`: titulo principal da tela inicial.
- `sector.tagline`: subtitulo em amarelo logo abaixo.
- `sector.description`: paragrafo de apresentacao.
- `theme.*`: cores de toda a interface.

---

## 2. Aplicativos e links -> `data/catalog.json`

Cada item da lista `apps` e um aplicativo que aparece no menu lateral e na home.

```json
{
  "apps": [
    {
      "id": "relatorio-producao",                         // identificador unico (sem espacos)
      "nome": "Relatorio de Producao",                    // nome exibido
      "descricao": "Texto que aparece na tela de detalhe do app.",
      "imagem": "assets/images/relatorio-producao.png",   // caminho da imagem (ver secao 3)
      "tipo": "xlsx",                                      // "exe", "xlsx" ou "xlsm"
      "download_url": "https://SEU-SITE.sharepoint.com/.../arquivo.xlsx?download=1",
      "versao": "1.2.0"
    }
  ]
}
```

Campos:
- `id`: unico, sem espacos (usado para criar a pasta de download).
- `nome`, `descricao`, `versao`: textos exibidos.
- `tipo`: `"exe"` (executa), `"xlsx"` ou `"xlsm"` (abre no Excel).
- `imagem`: caminho relativo comecando por `assets/images/`.
- `download_url`: **link real do arquivo no SharePoint**. Dica: adicione `?download=1` ao
  final do link de compartilhamento para forcar o download direto.

Para adicionar um app: copie um bloco `{ ... }` dentro de `apps` e ajuste os campos.

---

## 3. Imagens dos aplicativos -> `assets/images/`

- Coloque uma imagem para cada app; o nome do arquivo deve bater com o campo `imagem`
  do catalogo (ex.: `assets/images/relatorio-producao.png`).
- Formato recomendado: PNG ou JPG, proporcao ~16:9 (ex.: 1040x600).
- Se a imagem nao existir, a Suite mostra automaticamente um placeholder (nada quebra).

---

## 4. Catalogo remoto (opcional)

Se um dia voce hospedar um `catalog.json` acessivel por URL (ex.: SharePoint), basta
preencher em `settings.json`:

```json
"catalog": { "local_file": "data/catalog.json", "remote_url": "https://.../catalog.json" }
```

A Suite passa a ler a lista de apps da URL (com o arquivo local como fallback), permitindo
atualizar o catalogo sem redistribuir o programa.

---

## Resumo da privacidade

- Repo publico = codigo + `*.example` + este guia. **Sem dados internos.**
- Seus dados reais ficam em `settings.json`, `data/catalog.json` e `assets/images/*`,
  todos no `.gitignore`. Eles **nunca** sao enviados ao repositorio.
