# Arquitetura De Persistencia

## Estrutura Definitiva

```text
database/
  raw/
    licitacon_raw.sqlite
  operational/
    licitacon_search.sqlite
  app/
    app.sqlite
  migrations/
  etl/
```

## RAW

O RAW e temporario, minimo e reconstruivel. Ele deve armazenar apenas anos recentes e tabelas realmente usadas.

Padroes atuais:

- caminho: `database/raw/licitacon_raw.sqlite`
- ano minimo: `2024`
- tabelas padrao: `licitacao`, `item`, `pessoas`, `item_prop`, `proposta`, `licitante`

`pessoas` continua no RAW porque a consolidacao atual usa essa tabela para resolver vencedor/fornecedor sem quebrar a pesquisa existente. Tabelas como `comissao`, `membrocons`, `memcomissao`, `documento_lic`, `dotacao_lic` e `evento_lic` ficam fora do import padrao.

## OPERATIONAL

O operacional e o banco de runtime da pesquisa.

- caminho: `database/operational/licitacon_search.sqlite`
- contem `base_pesquisa_operacional`
- contem FTS5 (`base_pesquisa_operacional_fts`)
- contem indices voltados a busca, score, filtros e lote

Em `SEARCH_DB_MODE=auto`, a aplicacao tenta o operacional primeiro e cai para RAW apenas se necessario.

## APP

O APP e separado do operacional.

- caminho: `database/app/app.sqlite`
- guarda usuarios, fornecedores, cotacoes, pesquisas e fontes salvas
- futuramente deve receber perfis, cestas persistentes, favoritos, sessoes e auditoria

## Plano De Migracao Gradual

1. Manter `SEARCH_DB_MODE=auto` e validar que Flask usa `database/operational/licitacon_search.sqlite`.
2. Migrar `pesquisa_precos_app.sqlite` para `database/app/app.sqlite` quando houver usuarios/dados reais a preservar.
3. Recriar RAW com anos `>= 2024`:

```powershell
python -m database.raw.importar_licitacon --pasta bases_dados/licitacon_anos/2024.csv bases_dados/licitacon_anos/2025.csv bases_dados/licitacon_anos/2026.csv
```

4. Recriar operacional a partir do RAW enxuto:

```powershell
python -m database.etl.etl_licitacon --origem database/raw/licitacon_raw.sqlite --saida database/operational/licitacon_search.sqlite
```

5. Depois da equivalencia funcional, tirar `licitacon.sqlite` da rotina de runtime e manter apenas como backup temporario/offline.

## Deploy, Backup E Custo

- Subir para web com `database/operational/licitacon_search.sqlite` e `database/app/app.sqlite`, evitando RAW no runtime.
- Fazer backup frequente do APP, pois ele guarda dados de usuarios e auditoria.
- Recriar o operacional por ETL quando houver atualizacao do LicitaCon, em vez de sincronizar RAW pesado.
- Usar RAW apenas em job offline/incremental, com janela de anos controlada.
- Manter SQLite nesta fase; Postgres/Supabase pode entrar quando autenticacao multiusuario e auditoria exigirem concorrencia maior.
