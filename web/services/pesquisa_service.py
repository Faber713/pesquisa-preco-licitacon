import logging
import time

from ia.ia_criterios import extrair_criterios_com_ia
from search.busca import buscar_item, juntar_resultados
from search.models import item_valido
from search.providers.pncp_provider import PNCPProvider
from search.sqlite_repository import carregar_candidatos_runtime
from config.app_settings import MIN_RESULTADOS_DESEJADOS


logger = logging.getLogger("pesquisa")


def executar_pesquisa_item(
    descricao,
    qtd_min,
    qtd_max,
    *,
    limite,
    search_db_mode,
    raw_path,
    operational_path,
    fontes=None,
):
    inicio = time.perf_counter()
    fontes = [str(fonte).lower() for fonte in (fontes or ["licitacon"])]
    tempo_ia_ms = 0
    tempo_sqlite_ms = 0
    tempo_score_ms = 0
    tempo_pncp_ms = 0
    inicio_ia = time.perf_counter()
    criterios = extrair_criterios_com_ia(descricao)
    tempo_ia_ms = round((time.perf_counter() - inicio_ia) * 1000, 2)
    candidatos = []
    resultados_rigido = []
    resultados_relaxado = []
    resultados_amplo = []
    sqlite_search = {}

    if "licitacon" in fontes:
        inicio_sqlite = time.perf_counter()
        candidatos = carregar_candidatos_runtime(
            descricao_busca=descricao,
            criterios=criterios,
            limite=limite,
            mode=search_db_mode,
            raw_path=raw_path,
            operational_path=operational_path,
            tabela="base_pesquisa",
            ordenar_por_relevancia=False,
        )
        sqlite_search = candidatos.attrs.get("sqlite_search", {})
        tempo_sqlite_ms = round((time.perf_counter() - inicio_sqlite) * 1000, 2)
        inicio_score = time.perf_counter()
        resultados_rigido = buscar_item(
            candidatos,
            descricao,
            qtd_min,
            qtd_max,
            criterios,
            modo="rigido",
            exigir_homologacao=True,
        )
        resultados_relaxado = buscar_item(
            candidatos,
            descricao,
            qtd_min,
            qtd_max,
            criterios,
            modo="relaxado",
            exigir_homologacao=True,
        )
        resultados_amplo = buscar_item(
            candidatos,
            descricao,
            qtd_min,
            qtd_max,
            criterios,
            modo="amplo",
            exigir_homologacao=True,
        )
        tempo_score_ms = round((time.perf_counter() - inicio_score) * 1000, 2)
    resultados = juntar_resultados(
        resultados_rigido,
        resultados_relaxado,
        resultados_amplo,
    )
    resultados_pncp = []
    pncp_stats = {}
    if "pncp" in fontes:
        inicio_pncp = time.perf_counter()
        pncp_provider = PNCPProvider()
        resultados_pncp = pncp_provider.buscar(
            descricao,
            criterios=criterios,
            limite=10,
            dias=180,
            max_paginas=1,
        )
        pncp_stats = getattr(pncp_provider, "last_stats", {}) or {}
        tempo_pncp_ms = round((time.perf_counter() - inicio_pncp) * 1000, 2)
        resultados_pncp = [resultado for resultado in resultados_pncp if item_valido(resultado)]
        resultados.extend(resultados_pncp)
        resultados = [resultado for resultado in resultados if item_valido(resultado)]
        resultados = sorted(resultados, key=lambda item: item.get("score", 0), reverse=True)

    tempo_total_ms = round((time.perf_counter() - inicio) * 1000, 2)
    scores = [r.get("score", 0) for r in resultados]
    estatisticas = {
        "candidatos": len(candidatos),
        "rigido": len(resultados_rigido),
        "relaxado": len(resultados_relaxado),
        "amplo": len(resultados_amplo),
        "pncp": len(resultados_pncp),
        "total": len(resultados),
        "minimo_desejado": MIN_RESULTADOS_DESEJADOS,
        "sqlite_search": sqlite_search,
        "tempo_total_ms": tempo_total_ms,
        "tempo_ia_ms": tempo_ia_ms,
        "tempo_sqlite_ms": tempo_sqlite_ms,
        "tempo_pncp_ms": tempo_pncp_ms,
        "tempo_score_ms": tempo_score_ms,
        "registros_processados": len(candidatos) + len(resultados_pncp),
        "pncp_pipeline": pncp_stats,
        "score_max": max(scores) if scores else 0,
        "score_min": min(scores) if scores else 0,
        "fontes": fontes,
    }

    logger.info(
        "Pesquisa item descricao_original=%r descricao_resumida=%r fontes=%s resultados=%s score_max=%s score_min=%s candidatos=%s tempo_total_ms=%s tempo_sqlite_ms=%s tempo_pncp_ms=%s tempo_ia_ms=%s tempo_score_ms=%s registros_processados=%s sqlite=%s",
        descricao,
        criterios.get("descricao_resumida", descricao),
        fontes,
        len(resultados),
        estatisticas["score_max"],
        estatisticas["score_min"],
        len(candidatos),
        tempo_total_ms,
        tempo_sqlite_ms,
        tempo_pncp_ms,
        tempo_ia_ms,
        tempo_score_ms,
        estatisticas["registros_processados"],
        estatisticas["sqlite_search"],
    )
    return criterios, resultados, estatisticas
