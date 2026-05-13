# Auditoria de Armazenamento e Dependencias

Data: 2026-05-13

Esta auditoria diagnostica o uso de disco do projeto e separa dados de runtime, dados RAW/ETL, artefatos de build e caches. Nenhum arquivo foi removido nesta etapa.

## Resumo Executivo

O projeto ocupa aproximadamente:

- 11.16 GB em bytes decimais.
- 10.39 GiB em base binaria.

Os maiores blocos sao:

| Bloco | Tamanho aproximado | Papel atual |
|---|---:|---|
| `licitacon.sqlite` | 6.02 GB | Banco bruto/consolidado ainda usado em runtime por Flask e Streamlit |
| `bases_dados/` | 3.17 GB | CSVs crus do LicitaCon e bases municipais, usados para reimportacao |
| `database/operational/licitacon_search.sqlite` | 1.90 GB | Banco operacional novo, validado, ainda nao usado em runtime |
| `build/` | 64 MB | Artefato antigo de empacotamento/PyInstaller |
| `resultado_da_busca_item.csv` | 1.27 MB | Saida gerada de busca antiga |
| `__pycache__/` e caches de pacotes | < 1 MB | Regeneraveis |

## Maiores Pastas e Arquivos

### Pastas

| Caminho | Tamanho |
|---|---:|
| `licitacon.sqlite` | 6,022,922,240 bytes |
| `bases_dados/` | 3,171,897,241 bytes |
| `database/` | 1,898,759,821 bytes |
| `build/` | 64,013,630 bytes |
| `resultado_da_busca_item.csv` | 1,270,695 bytes |

### Top arquivos

| Arquivo | Tamanho |
|---|---:|
| `licitacon.sqlite` | 6,022,922,240 |
| `database/operational/licitacon_search.sqlite` | 1,898,688,512 |
| `bases_dados/licitacon_anos/2025.csv/item_prop.csv` | 368,817,931 |
| `bases_dados/licitacon_anos/2024.csv/item_prop.csv` | 317,448,709 |
| `bases_dados/licitacon_anos/2025.csv/item.csv` | 307,192,071 |
| `bases_dados/licitacon_anos/2024.csv/item.csv` | 274,756,980 |
| `bases_dados/licitacon_anos/2025.csv/documento_lic.csv` | 231,547,341 |
| `bases_dados/licitacon_anos/2024.csv/documento_lic.csv` | 193,342,677 |
| `bases_dados/licitacon_anos/2025.csv/pessoas.csv` | 187,334,528 |
| `bases_dados/licitacon_anos/2026.csv/pessoas.csv` | 187,334,528 |
| `bases_dados/licitacon_anos/2024.csv/pessoas.csv` | 186,908,283 |

## Distribuicao Por Tipo

| Tipo | Quantidade | Tamanho |
|---|---:|---:|
| `.sqlite` | 3 | 7,921,643,520 bytes |
| `.csv` | 212 | 3,173,143,330 bytes |
| `.pkg` | 1 | 42,471,742 bytes |
| `.pyz` | 1 | 13,792,697 bytes |
| `.html` | 4 | 4,497,822 bytes |
| `.zip` | 1 | 1,388,172 bytes |
| `.pyc` | 53 | 663,979 bytes |

## Bancos SQLite

### `licitacon.sqlite`

Tamanho: 6.02 GB.

Uso apos a migracao gradual:

- `app_web.py` e Flask ainda mantem fallback para este banco via `LICITACON_SQLITE_PATH`.
- `search/sqlite_repository.py` usa este banco quando `SEARCH_DB_MODE=raw` ou quando `SEARCH_DB_MODE=auto` precisa acionar fallback.

Tabelas principais:

| Tabela | Linhas | Uso |
|---|---:|---|
| `base_pesquisa` | 3,084,249 | Consolidada geral usada para busca |
| `base_historica_municipios` | 254,244 | Consolidada regional |
| `base_pesquisa_fts` | 3,084,249 | FTS5 atual sobre a base geral |
| `item` | 3,084,249 | RAW importado |
| `licitacao` | 366,132 | RAW importado |
| `pessoas` | 4,809,511 | RAW importado |
| `municipio_item` | 254,244 | RAW regional |
| `municipio_licitacao` | 26,708 | RAW regional |
| `municipio_pessoas` | 45,649 | RAW regional |

Diagnostico: mistura RAW, tabelas consolidadas e FTS5 no mesmo arquivo. E poderoso para desenvolvimento/ETL, mas pesado demais para runtime e deploy web.

### `database/operational/licitacon_search.sqlite`

Tamanho: 1.90 GB.

Banco operacional enxuto. Apos a migracao gradual, e usado como fonte principal quando `SEARCH_DB_MODE=auto` ou `SEARCH_DB_MODE=operational`.

Tabelas:

| Tabela | Linhas |
|---|---:|
| `base_pesquisa_operacional` | 1,372,118 |
| `base_pesquisa_operacional_fts` | 1,372,118 |

Fontes:

| Fonte | Linhas |
|---|---:|
| LicitaCon geral | 1,203,833 |
| Historico regional | 168,285 |

Diagnostico: melhor candidato para runtime. Ja elimina registros sem homologacao/fornecedor/valor valido e junta geral + regional em uma tabela.

### `pesquisa_precos_app.sqlite`

Tamanho: 32 KB.

Uso:

- Banco transacional da aplicacao.
- Usuarios, fornecedores, cotacoes, pesquisas e fontes registradas.

Deve permanecer no runtime. Nao e redundante.

## CSVs RAW

`bases_dados/` ocupa 3.17 GB:

| Subpasta | Tamanho |
|---|---:|
| `bases_dados/licitacon_anos` | 2.99 GB |
| `bases_dados/municipios_regionais` | 180.69 MB |
| `bases_dados/leis_joia` | 24 KB |

Os CSVs sao necessarios apenas para:

- reimportar `licitacon.sqlite`;
- auditoria/reproducibilidade;
- atualizar base quando houver novos arquivos TCE-RS;
- reconstruir bancos do zero.

Nao sao necessarios para runtime se o banco operacional estiver pronto e validado.

## Duplicacoes Detectadas

Duplicados exatos por hash:

| Arquivos | Tamanho |
|---|---:|
| `2025.csv/pessoas.csv` e `2026.csv/pessoas.csv` | 187,334,528 |
| `2025.csv/memcomissao.csv` e `2026.csv/memcomissao.csv` | 12,522,279 |
| `2025.csv/comissao.csv` e `2026.csv/comissao.csv` | 2,005,785 |

Interpretacao: parte dos CSVs anuais traz arquivos idempotentes/repetidos. Eles podem ser arquivados/comprimidos futuramente, mas nao devem ser removidos sem uma politica de reproducibilidade.

## Artefatos Regeneraveis

Podem ser removidos depois de confirmacao, pois sao regeneraveis:

- `build/` (64 MB): artefato de empacotamento antigo.
- `__pycache__/` em varias pastas: cache Python.
- `resultado_da_busca_item.csv`: saida gerada.

Impacto de remocao:

- `build/`: nenhum impacto no Flask/Streamlit; afeta apenas empacotamento antigo.
- `__pycache__/`: nenhum impacto, Python recria.
- `resultado_da_busca_item.csv`: perde uma saida antiga, nao o sistema.

## Dependencias Reais Do Sistema

### Runtime Flask atual

Depende de:

- codigo em `web/`, `search/`, `ia/`, `utils/`;
- `database/operational/licitacon_search.sqlite` por padrao em `SEARCH_DB_MODE=auto`;
- `licitacon.sqlite` como fallback ou quando `SEARCH_DB_MODE=raw`;
- `pesquisa_precos_app.sqlite` indiretamente apenas se funcionalidades de storage/auth forem conectadas ao Flask no futuro.

Nao depende de CSVs em `bases_dados/` para runtime.

### Runtime Streamlit atual

Depende de:

- `app_web.py`;
- `search/`, `ia/`, `reports/`, `utils/`;
- `database/operational/licitacon_search.sqlite` por padrao em `SEARCH_DB_MODE=auto`;
- `licitacon.sqlite` como fallback ou quando `SEARCH_DB_MODE=raw`;
- `pesquisa_precos_app.sqlite`.

### ETL/importacao

Depende de:

- `bases_dados/`;
- `database/raw/importar_licitacon.py`;
- `database/raw/importar_municipios_regionais.py`;
- `database/etl/etl_licitacon.py`;
- `licitacon.sqlite` como origem atual do ETL operacional.

## Redundancia Arquitetural

### CSVs x `licitacon.sqlite`

Os CSVs sao RAW. O SQLite bruto e uma materializacao importada desses CSVs. Manter ambos no projeto principal duplica armazenamento, mas preserva reproducibilidade.

Recomendacao: CSVs devem sair do workspace de runtime e ir para `archive/`, disco externo, NAS, storage em nuvem ou pasta de dados fora do repo.

### `licitacon.sqlite` x `licitacon_search.sqlite`

`licitacon.sqlite` contem RAW + consolidado + FTS. `licitacon_search.sqlite` contem apenas dados operacionais de pesquisa.

Recomendacao: manter ambos durante a validacao. Depois que Flask usar o operacional com equivalencia aceitavel, `licitacon.sqlite` deve virar fonte de ETL offline, nao runtime.

### Tabelas normais x FTS

FTS duplica texto para acelerar busca. Essa duplicacao e esperada e justificada em runtime. No banco operacional, a duplicacao e muito mais controlada.

## Estrategia Recomendada

### Curto Prazo

Nao apagar nada ainda.

1. Migrar Flask para ler `database/operational/licitacon_search.sqlite` por variavel de ambiente.
2. Comparar resultados Flask com banco bruto em itens reais.
3. Validar se `base_historica_municipios` operacional supre a busca regional.
4. Criar checklist de equivalencia de resultados.

### Limpeza Segura Apos Validacao

Candidatos a remocao/arquivo:

| Item | Acao recomendada | Ganho aproximado |
|---|---|---:|
| `build/` | remover ou arquivar | 64 MB |
| `__pycache__/` | remover | < 1 MB |
| `resultado_da_busca_item.csv` | arquivar/remover | 1.27 MB |
| CSVs `bases_dados/` | comprimir/arquivar fora do runtime | 3.17 GB |
| `licitacon.sqlite` | tirar do runtime depois da migracao operacional | 6.02 GB |

### Arquitetura Ideal Futura

```text
project/
  web/
  search/
  ia/
  reports/
  utils/
  database/
    etl/
    raw/              # scripts, nao necessariamente dados
    operational/
      licitacon_search.sqlite

external-data/
  raw_licitacon/
    2024/
    2025/
    2026/
  archive/
    licitacon_raw_2024_2026.zip
  staging/
    licitacon.sqlite
```

Runtime/deploy deve conter:

- codigo;
- `database/operational/licitacon_search.sqlite`;
- `pesquisa_precos_app.sqlite` ou banco transacional equivalente;
- arquivos estaticos/templates.

Runtime/deploy nao deve conter:

- CSVs crus;
- `licitacon.sqlite` bruto;
- `build/`;
- caches Python;
- saidas antigas.

## Avaliacao: Manter Banco Bruto?

Sim, por enquanto, mas como fonte de ETL e backup tecnico, nao como runtime definitivo.

Quando o Flask puder usar `licitacon_search.sqlite`, o banco bruto pode ser movido para:

- `database/raw/` fora do deploy;
- disco externo;
- storage local compartilhado;
- backup compactado.

## Opcoes Futuras

### Comprimir CSVs

Vale a pena. CSV comprime muito bem. Pode reduzir 3.17 GB para algo significativamente menor. Ideal para archive, nao para runtime.

### Dividir bancos por ano

Pode valer para ETL incremental, mas nao para runtime. Para busca operacional, uma tabela unica com FTS5 e filtros por ano e fonte e mais simples.

### Banco hibrido

Recomendado:

- SQLite operacional para runtime local/deploy simples.
- RAW em storage externo.
- Futuramente PostgreSQL/pg_trgm ou OpenSearch apenas se houver multiusuario, servidor central ou volume muito maior.

### Storage externo

Recomendado para:

- CSVs crus;
- snapshots anuais;
- `licitacon.sqlite` bruto;
- backups do operacional.

## Plano Incremental De Limpeza

1. Congelar estado atual: nao apagar.
2. Migrar Flask para modo operacional opcional.
3. Testar 20-50 itens reais e comparar resultados.
4. Se aprovado, definir `licitacon_search.sqlite` como runtime padrao.
5. Arquivar `bases_dados/` fora do projeto.
6. Arquivar `licitacon.sqlite` como fonte ETL offline.
7. Remover `build/`, `__pycache__/` e saidas antigas.
8. Documentar processo de rebuild:
   - CSVs RAW -> `licitacon.sqlite`;
   - `licitacon.sqlite` -> `licitacon_search.sqlite`;
   - runtime Flask -> `licitacon_search.sqlite`.
