import logging
import time

from ia.ia_criterios import extrair_criterios_com_ia
from search.models import item_valido
from search.price_validation import classificar_precos, gerar_justificativa_automatica
from search.providers.licitacon_provider import LicitaConProvider
from search.providers.pncp_provider import PNCPProvider
from search.sources import FontePesquisa, filtrar_fontes_ativas, fonte_confiabilidade, normalizar_fontes
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
    criterios_override=None,
    estrategia_busca="inteligente",
):
    inicio = time.perf_counter()
    fontes_solicitadas = normalizar_fontes(fontes or [FontePesquisa.LICITACON.value])
    fontes = filtrar_fontes_ativas(fontes_solicitadas)
    if not fontes:
        fontes = [FontePesquisa.LICITACON.value]
    tempo_ia_ms = 0
    tempo_sqlite_ms = 0
    tempo_score_ms = 0
    tempo_pncp_ms = 0
    inicio_ia = time.perf_counter()
    criterios = dict(criterios_override) if criterios_override else extrair_criterios_com_ia(descricao)
    tempo_ia_ms = round((time.perf_counter() - inicio_ia) * 1000, 2)
    candidatos = []
    resultados_rigido = []
    resultados_relaxado = []
    resultados_amplo = []
    sqlite_search = {}
    provider_stats = {}

    if FontePesquisa.LICITACON.value in fontes:
        logger.debug("[provider_start] provider=licitacon descricao=%r", descricao)
        inicio_sqlite = time.perf_counter()
        licitacon_provider = LicitaConProvider()
        resultados_licitacon, licitacon_stats = licitacon_provider.buscar(
            descricao,
            criterios=criterios,
            qtd_min=qtd_min,
            qtd_max=qtd_max,
            limite=limite,
            search_db_mode=search_db_mode,
            raw_path=raw_path,
            operational_path=operational_path,
            estrategia_busca=estrategia_busca,
        )
        candidatos = [None] * int(licitacon_stats.get("candidatos", 0))
        sqlite_search = licitacon_stats.get("sqlite_search", {})
        tempo_sqlite_ms = round((time.perf_counter() - inicio_sqlite) * 1000, 2)
        tempo_score_ms = licitacon_stats.get("tempo_ms", 0)
        resultados_rigido = [r for r in resultados_licitacon if r.get("modo_busca") == "rigido"]
        resultados_relaxado = [r for r in resultados_licitacon if r.get("modo_busca") == "relaxado"]
        resultados_amplo = [r for r in resultados_licitacon if r.get("modo_busca") == "amplo"]
        resultados = resultados_licitacon
        provider_stats["licitacon"] = licitacon_stats
    else:
        resultados = []
    resultados_pncp = []
    pncp_stats = {}
    if FontePesquisa.PNCP.value in fontes:
        logger.debug("[provider_start] provider=pncp descricao=%r", descricao)
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
        provider_stats["pncp"] = pncp_stats
        logger.debug("[provider_results] provider=pncp resultados=%s tempo_ms=%s", len(resultados_pncp), tempo_pncp_ms)

    resultados, estatisticas_precos = classificar_precos(resultados)
    justificativa_automatica = gerar_justificativa_automatica(
        fontes,
        total_precos=len(resultados),
        estatisticas=estatisticas_precos,
    )
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
        "providers": provider_stats,
        "source_reliability": {fonte: fonte_confiabilidade(fonte) for fonte in fontes},
        "score_max": max(scores) if scores else 0,
        "score_min": min(scores) if scores else 0,
        "fontes": fontes,
        "estrategia_busca": estrategia_busca,
        "fontes_solicitadas": fontes_solicitadas,
        "precos": estatisticas_precos,
        "justificativa_automatica": justificativa_automatica,
        "validos": sum(1 for r in resultados if r.get("status_validacao") == "VALIDO"),
        "suspeitos": sum(1 for r in resultados if r.get("status_validacao") in {"SUSPEITO", "INEXEQUIVEL", "EXCESSIVAMENTE ELEVADO"}),
        "incompativeis": sum(1 for r in resultados if r.get("status_validacao") == "INCOMPATIVEL"),
    }

    logger.debug(
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
