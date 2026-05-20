# Hospedagem web

Este projeto roda como aplicacao Flask com HTML, CSS e JavaScript.

## Variaveis e secrets

Configure as chaves no ambiente da hospedagem, nunca no codigo:

```text
SERPAPI_KEY=sua_chave_serpapi
APP_AUTH_ENABLED=1
APP_ADMIN_EMAIL=seu_email
APP_ADMIN_PASSWORD=sua_senha_forte
APP_ADMIN_NAME=Administrador
LICITACON_SQLITE_PATH=database/raw/licitacon_raw.sqlite
SEARCH_DB_PATH=database/operational/licitacon_search.sqlite
SEARCH_DB_MODE=auto
APP_DB_PATH=database/app/app.sqlite
APP_ENV=production
SECRET_KEY=troque_esta_chave
SESSION_COOKIE_SECURE=1
```

Se `APP_ADMIN_EMAIL` e `APP_ADMIN_PASSWORD` forem informados e ainda nao
existir usuario no banco `database/app/app.sqlite`, o administrador inicial e
criado automaticamente. A tela de login Flask fica como etapa futura.

## Rodar local

```powershell
.\.venv\Scripts\python.exe run.py
```

## Gunicorn

Em Linux:

```bash
gunicorn "run:app" --bind 0.0.0.0:8000 --workers 2
```

## Observacoes para hospedagem

- O arquivo RAW `database/raw/licitacon_raw.sqlite` pode ficar grande para plataformas gratuitas comuns.
  Para o primeiro teste web, suba a aplicacao sem essa base e use CSV manual,
  PNCP, Internet e Fornecedores.
- Se hospedar a base em um volume/disco externo ou copiar o arquivo para outro
  caminho no servidor, configure `SEARCH_DB_PATH` com o operacional e use
  `LICITACON_SQLITE_PATH` apenas para ETL/fallback.
- Configure as variaveis no ambiente da hospedagem ou em `.env` local.
- O banco `database/app/app.sqlite` guarda usuarios, fornecedores, cotacoes e
  pesquisas salvas. Em hospedagem sem disco persistente, esses dados podem sumir
  a cada reinicio; depois vale migrar para Postgres/Supabase.
- O arquivo `.env` local esta no `.gitignore`; mantenha assim para nao publicar
  chaves.

## Base LicitaCon online

O RAW local pode ter varios GB. Mesmo quando a hospedagem aceita esse
tamanho em disco, carregar e consultar SQLite grande em uma maquina pequena pode
estourar memoria ou deixar a aplicacao lenta. Caminhos recomendados:

- Manter o deploy atual sem a base pesada e usar CSV manual/PNCP/Internet para
  validar a interface.
- Criar uma base reduzida, por exemplo somente anos recentes ou municipios de
  interesse, e gerar `database/raw/licitacon_raw.sqlite` e
  `database/operational/licitacon_search.sqlite` menores.
- Migrar `base_pesquisa` e `base_historica_municipios` para Postgres/Supabase e
  adaptar as funcoes de busca para consultar esse banco.
- Usar um servidor proprio com disco persistente se quiser manter SQLite grande.
