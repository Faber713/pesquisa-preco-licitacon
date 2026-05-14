# Pesquisa De Precos

Sistema local/web para pesquisa de precos em licitacoes publicas, com Flask,
SQLite, FTS5, ETL LicitaCon, score, cesta de precos e dossie HTML.

## Entry Points

```powershell
python run.py
python -m scripts.run_importacao --help
python -m scripts.run_etl --help
python -m scripts.run_busca_cli
```

## Estrutura

- `auth/`: autenticacao, senhas, permissoes e sessoes.
- `config/`: configuracoes da aplicacao, banco, busca, seguranca e providers.
- `database/`: RAW, OPERATIONAL, APP, ETL, migrations, seeds e backups.
- `exports/`: saidas finais CSV, HTML, PDF futuro e relatorios.
- `scripts/`: entrypoints operacionais.
- `search/`: busca, score, repositorio SQLite e providers.
- `storage/`: cache, uploads, logs, temporarios e arquivos internos.
- `web/`: aplicacao Flask, templates Jinja, APIs JSON e assets estaticos.
