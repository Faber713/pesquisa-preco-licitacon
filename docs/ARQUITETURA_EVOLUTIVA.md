# Arquitetura Evolutiva - Pesquisa de Precos Publicos

Este documento define uma evolucao incremental para transformar o projeto atual em uma plataforma profissional, preservando compatibilidade com os scripts e a interface existentes.

## Principios

- Nao reescrever do zero.
- Preservar os pontos de entrada atuais, especialmente `app_web.py`, `busca.py` e importadores.
- Extrair responsabilidades aos poucos, com adaptadores finos entre codigo legado e novos servicos.
- Manter rastreabilidade: toda decisao de compatibilidade, descarte, fonte e metodologia deve poder ser explicada em auditoria.
- Separar busca de candidatos, avaliacao tecnica, formacao de cesta, conformidade normativa e apresentacao.

## Diagnostico Atual

O sistema ja possui os blocos essenciais:

- `ia_criterios.py`: interpretacao da descricao e extracao de criterios.
- `busca.py`: varredura de candidatos, filtros de homologacao, quantidade e aderencia.
- `score.py`: pontuacao textual e tecnica.
- `regras_tecnicas.py` e `regras_produtos_eletricos.py`: validacoes especializadas.
- `provedores_precos.py`: fontes externas como PNCP, web e fornecedores.
- `fontes_preco.py`: normalizacao de fontes.
- `normativos.py`: conformidade, perfis normativos e relatorios.
- `app_storage.py`: persistencia da aplicacao.
- `app_web.py`: UI, orquestracao, processamento em lote, relatorios e parte da busca SQLite.

O principal risco arquitetural hoje e que `app_web.py` concentra muitas responsabilidades. Isso dificulta testes, performance, troca futura de Streamlit/Flask/FastAPI e evolucao da busca.

## Estrutura Alvo

Estrutura sugerida para evolucao gradual:

```text
pesquisa_precos/
  core/
    criterios.py
    matching.py
    scoring.py
    regras.py
    normalizacao.py
  search/
    pipeline.py
    sqlite_repository.py
    fts.py
    filtros.py
  providers/
    licitacon.py
    pncp.py
    web.py
    fornecedores.py
  compliance/
    normativos.py
    auditoria.py
  storage/
    app_db.py
    migrations.py
  reports/
    html.py
    excel.py
    pdf.py
  web/
    streamlit_app.py
  api/
    routes.py
```

No primeiro momento, estes arquivos podem apenas importar e encapsular funcoes existentes. A migracao real acontece modulo por modulo.

## Pipeline De Busca Recomendada

A pipeline profissional deve ter cinco etapas separadas:

1. Interpretacao do item
   - Entrada: descricao, quantidade, unidade, contexto da licitacao.
   - Saida: termos obrigatorios, importantes, exclusoes, descricao generica, exigencias tecnicas e justificativa.

2. Recuperacao rapida de candidatos
   - LicitaCon SQLite com FTS5.
   - PNCP por termos candidatos.
   - Historico local e fornecedores.
   - Internet somente como fonte auxiliar e com maior cuidado probatorio.

3. Re-ranking tecnico
   - RapidFuzz.
   - termos obrigatorios/importantes.
   - regras de incompatibilidade.
   - penalidades por termos genericos.
   - validacao de quantidade, homologacao, data e fonte.

4. Formacao da cesta
   - metas por origem.
   - descarte de outliers.
   - mediana/media/menor preco conforme regra configurada.
   - aprovacao manual defensavel.

5. Dossie de auditoria
   - criterios usados.
   - fontes consultadas.
   - candidatos descartados e motivo.
   - metodologia.
   - evidencias e links.
   - perfil normativo aplicado.

## FTS5 No SQLite

Criar tabelas virtuais FTS5 para reduzir a quantidade de linhas que chegam ao fuzzy matching.

Exemplo conceitual:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS base_pesquisa_fts
USING fts5(
  descricao,
  objeto,
  orgao,
  vencedor,
  content='base_pesquisa',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```

Fluxo recomendado:

- IA/local gera termos de recuperacao.
- FTS retorna top N candidatos.
- SQL aplica filtros baratos: ano, municipio, homologacao, valor valido.
- Python aplica score e regras tecnicas.
- UI mostra score, motivo e evidencias.

FTS deve ser usado como recuperador, nao como decisor final. A decisao defensavel continua sendo feita pelo score tecnico e revisao humana.

## Indices SQLite Prioritarios

Para a base grande, criar indices somente onde houver filtros frequentes:

```sql
CREATE INDEX IF NOT EXISTS idx_base_pesquisa_ano ON base_pesquisa(ano);
CREATE INDEX IF NOT EXISTS idx_base_pesquisa_orgao ON base_pesquisa(orgao);
CREATE INDEX IF NOT EXISTS idx_base_pesquisa_modalidade ON base_pesquisa(modalidade);
CREATE INDEX IF NOT EXISTS idx_base_historica_municipio ON base_historica_municipios(municipio);
CREATE INDEX IF NOT EXISTS idx_base_historica_grupo ON base_historica_municipios(grupo_regional);
```

Antes de criar indices em base de 8 GB, validar nomes reais de colunas e medir tempo de importacao versus tempo de consulta.

## APIs Internas

Mesmo usando Streamlit, o backend deve oferecer funcoes estaveis:

```python
executar_pesquisa_item(request: PesquisaItemRequest) -> PesquisaItemResult
executar_pesquisa_lote(request: PesquisaLoteRequest) -> PesquisaLoteResult
buscar_candidatos_licitacon(request: BuscaLicitaConRequest) -> list[FontePreco]
avaliar_conformidade(request: ConformidadeRequest) -> ConformidadeResult
```

Essas APIs internas permitem migrar depois para Flask, FastAPI ou outro frontend sem reescrever a inteligencia.

## Plano Incremental

### Fase 1 - Organizacao Sem Quebra

- Criar pacote `pesquisa_precos/`.
- Criar wrappers que chamam os modulos atuais.
- Mover logica pura de `app_web.py` para servicos novos, mantendo imports antigos funcionando.
- Adicionar testes pequenos para normalizacao, score e filtros criticos.

### Fase 2 - Repositorio SQLite

- Extrair funcoes `base_sqlite_disponivel`, `tabela_sqlite_existe`, `montar_termos_sqlite` e `carregar_candidatos_sqlite`.
- Centralizar `PRAGMA`, conexao read-only quando possivel e limites.
- Preparar comandos de criacao/reconstrucao FTS5.

### Fase 3 - Pipeline Hibrida

- Criar `search/pipeline.py`.
- Rodar recuperacao por FTS primeiro.
- Aplicar fuzzy e regras tecnicas depois.
- Retornar explicacoes: termos encontrados, faltantes, exclusoes, alertas, origem e etapa.

### Fase 4 - Auditoria E Dossie

- Persistir snapshots dos criterios da IA.
- Persistir versao das regras usadas.
- Registrar descartes e justificativas.
- Gerar dossie com trilha completa de decisao.

### Fase 5 - Plataforma

- Separar frontend Streamlit da camada de aplicacao.
- Criar API Flask/FastAPI somente depois que os servicos estiverem estaveis.
- Avaliar PostgreSQL com `pg_trgm` e full-text search se houver concorrencia, multiusuario real ou necessidade de servidor central.

## Decisoes Arquiteturais

### SQLite permanece valido agora

Com uma base local grande, SQLite ainda e adequado para uso municipal local, desde que a busca seja indexada e a aplicacao evite varreduras completas. PostgreSQL deve ser uma evolucao por necessidade operacional, nao por ansiedade tecnica.

### IA nao deve decidir sozinha

A IA deve interpretar descricoes e sugerir termos. A aceitacao final precisa combinar regras deterministicas, evidencia documental e revisao humana.

### Matching defensavel exige explicacao

Cada resultado deve expor:

- por que foi encontrado;
- quais termos obrigatorios apareceram;
- quais faltaram;
- quais regras tecnicas foram aplicadas;
- se houve alerta de quantidade, data, fonte ou especificacao;
- por que foi aprovado ou descartado.

## Proximo Passo Recomendado

O primeiro refactor seguro e extrair a busca SQLite de `app_web.py` para um modulo dedicado, mantendo as funcoes antigas como chamadas delegadas. Isso reduz o tamanho do arquivo principal e prepara FTS5 sem mexer na UI.
