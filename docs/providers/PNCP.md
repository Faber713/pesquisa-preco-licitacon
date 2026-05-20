# Provider PNCP

## Fonte Oficial

- Portal PNCP: `https://pncp.gov.br`
- Swagger de consulta: `https://pncp.gov.br/api/consulta/swagger-ui/index.html`
- API de consulta: `https://pncp.gov.br/api/consulta`
- API detalhada de compras/itens: `https://pncp.gov.br/api/pncp`

As consultas de dados abertos do PNCP sao publicas e nao exigem login para leitura.

## Endpoints Usados

### Contratacoes por periodo de propostas

```text
GET /api/consulta/v1/contratacoes/proposta
```

Parametros principais:

- `dataFinal`: obrigatorio, formato `AAAAMMDD`.
- `dataInicial`: opcional, formato `AAAAMMDD`.
- `codigoModalidadeContratacao`: obrigatorio.
- `pagina`: paginacao iniciada em `1`.
- `uf`: opcional.
- `codigoMunicipioIbge`: opcional.
- `cnpj`: opcional.
- `tamanhoPagina`: opcional quando aceito pelo servico.

### Contratacoes por periodo de publicacao

```text
GET /api/consulta/v1/contratacoes/publicacao
```

Parametros principais:

- `dataInicial`: obrigatorio, formato `AAAAMMDD`.
- `dataFinal`: obrigatorio, formato `AAAAMMDD`.
- `codigoModalidadeContratacao`: obrigatorio.
- `pagina`: paginacao iniciada em `1`.

### Itens de uma compra

```text
GET /api/pncp/v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/itens
```

Retorna itens com descricao, quantidade, unidade, valor estimado, categoria e situacao.

### Resultado de um item

```text
GET /api/pncp/v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/itens/{numeroItem}/resultados
```

Pode retornar `204` quando ainda nao ha resultado homologado.

## Modalidades Padrao

O provider consulta, por padrao:

- `8`: dispensa;
- `6`, `7`, `9`, `5`: modalidades adicionais para ampliar cobertura.

Esses codigos devem ser ajustados conforme tabela de dominio oficial quando a tela de filtros PNCP for evoluida.

## Cache

O client grava respostas em:

```text
storage/cache/pncp_cache.sqlite
```

Tabela:

```text
cache_pncp(cache_key, url, params_json, response_json, status_code, created_at)
```

TTL padrao: 24 horas.

## Rastreabilidade

Cada resultado normalizado preserva o payload original em:

```python
resultado["raw"] = {
    "contratacao": ...,
    "item": ...,
    "resultados_item": ...,
}
```

Isso permite auditoria futura e reprocessamento sem perder a evidencia consultada.
