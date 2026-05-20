import logging
import time
from dataclasses import dataclass

from services.pncp_client import PNCPClient, PNCPClientError


logger = logging.getLogger("pncp")


@dataclass(frozen=True)
class PncpPage:
    endpoint: str
    pagina: int
    total_paginas: int
    registros: list
    payload: dict
    tempo_ms: float
    retries: int = 0


def registros_payload(payload):
    if isinstance(payload, dict):
        for chave in ("data", "items", "resultados"):
            valor = payload.get(chave)
            if isinstance(valor, list):
                return valor
    if isinstance(payload, list):
        return payload
    return []


def total_paginas_payload(payload, pagina_atual):
    if not isinstance(payload, dict):
        return pagina_atual
    for chave in ("totalPaginas", "total_pages", "totalPages", "paginas"):
        valor = payload.get(chave)
        if valor:
            try:
                return int(valor)
            except (TypeError, ValueError):
                pass
    return pagina_atual


class PNCPPaginator:
    def __init__(self, client=None):
        self.client = client or PNCPClient()

    def buscar_pagina(
        self,
        *,
        endpoint,
        data_inicial,
        data_final,
        pagina,
        tamanho_pagina=50,
        codigo_modalidade=8,
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
    ):
        inicio = time.perf_counter()
        if endpoint == "publicacao":
            payload = self.client.consultar_contratacoes_publicacao(
                data_inicial=data_inicial,
                data_final=data_final,
                codigo_modalidade=codigo_modalidade,
                pagina=pagina,
                uf=uf,
                codigo_municipio_ibge=codigo_municipio_ibge,
                cnpj=cnpj,
                tamanho_pagina=tamanho_pagina,
            )
        elif endpoint == "proposta":
            payload = self.client.consultar_contratacoes_proposta(
                data_inicial=data_inicial,
                data_final=data_final,
                codigo_modalidade=codigo_modalidade,
                pagina=pagina,
                uf=uf,
                codigo_municipio_ibge=codigo_municipio_ibge,
                cnpj=cnpj,
                tamanho_pagina=tamanho_pagina,
            )
        else:
            raise ValueError(f"Endpoint PNCP nao suportado: {endpoint}")

        registros = registros_payload(payload)
        total_paginas = total_paginas_payload(payload, pagina)
        tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
        return PncpPage(
            endpoint=endpoint,
            pagina=pagina,
            total_paginas=total_paginas,
            registros=registros,
            payload=payload,
            tempo_ms=tempo_ms,
        )

    def iterar_paginas(self, *, endpoint, data_inicial, data_final, pagina_inicial=1, max_paginas=None, **kwargs):
        pagina = int(pagina_inicial or 1)
        total_paginas = None
        while True:
            try:
                page = self.buscar_pagina(
                    endpoint=endpoint,
                    data_inicial=data_inicial,
                    data_final=data_final,
                    pagina=pagina,
                    **kwargs,
                )
            except PNCPClientError:
                logger.exception("PNCP pagina erro endpoint=%s pagina=%s", endpoint, pagina)
                raise
            total_paginas = page.total_paginas or total_paginas or pagina
            yield page
            if max_paginas and pagina >= int(max_paginas):
                break
            if pagina >= total_paginas:
                break
            if not page.registros:
                break
            pagina += 1

