# Suite Petrobras

Hub de aplicativos internos no estilo "Steam", desenvolvido em Python + [Flet](https://flet.dev).
A Suite apresenta o setor na tela inicial e, no menu lateral, lista os programas disponiveis
(`.exe` e `.xlsx`). Cada aplicativo tem uma tela de detalhe com imagem, descricao e botao de
Baixar / Instalar / Executar.

## Recursos

- Tela inicial com apresentacao do setor.
- Menu lateral com os aplicativos do catalogo.
- Tela de detalhe: imagem, versao, descricao e acao dinamica (Baixar -> Executar).
- Download a partir de link (inicialmente SharePoint) com **duas estrategias**:
  1. Download direto via `requests`.
  2. Fallback: abre o link no navegador para download manual e permite apontar o arquivo baixado.
- Catalogo local (`data/catalog.json`) com camada preparada para catalogo remoto (SharePoint) no futuro.

## Estrutura

```
Suite-steam/
  data/catalog.json        # catalogo de apps (local)
  assets/images/           # logo e imagens dos apps
  src/
    main.py                # entrada da aplicacao Flet
    config.py              # constantes e textos do setor
    models.py              # modelos de dados
    catalog/provider.py    # provedores de catalogo (Local + Remoto/stub)
    services/
      storage.py           # pastas de dados e manifesto de instalados
      download_manager.py  # download (direto + fallback navegador)
      runner.py            # execucao/abertura dos arquivos
    ui/
      home_view.py         # tela inicial
      app_detail_view.py   # tela de detalhe do app
      components.py         # componentes (sidebar, cards)
```

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src/main.py
```

### Ambiente corporativo (proxy com inspecao SSL)

Na rede Petrobras o `pip` pode falhar com `CERTIFICATE_VERIFY_FAILED` (certificado
self-signed do proxy). Nesse caso, instale marcando os hosts do PyPI como confiaveis:

```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

O pacote `flet-desktop` (cliente da janela nativa) e baixado junto e tambem precisa do
acesso ao PyPI na primeira execucao.

## Configurando o catalogo

Edite `data/catalog.json`. Cada app:

```json
{
  "id": "meu-app",
  "nome": "Meu App",
  "descricao": "Descricao do aplicativo...",
  "imagem": "assets/images/meu-app.png",
  "tipo": "exe",
  "download_url": "https://petrobras.sharepoint.com/.../arquivo.exe?download=1",
  "versao": "1.0.0"
}
```

- `tipo`: `exe` ou `xlsx`.
- `download_url`: link direto do arquivo no SharePoint. Dica: adicione `?download=1` ao final do link de compartilhamento para forcar o download direto.

## SharePoint

O acesso via API do SharePoint no ambiente corporativo e restrito. Por isso a Suite tenta o
download direto e, se detectar uma pagina de login/autenticacao, abre o link no navegador para o
usuario baixar manualmente e depois apontar o arquivo. Assim e possivel validar na pratica qual
abordagem funciona no ambiente Petrobras.

## Dados locais

Arquivos baixados e o manifesto de instalacao ficam em:

```
%LOCALAPPDATA%/SuitePetrobras/
```
