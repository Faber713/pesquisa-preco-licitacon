import logging
import time

from ia.ia_criterios import extrair_criterios_com_ia, extrair_criterios_simples
from search.busca import buscar_item, juntar_resultados
from search.models import item_valido
from search.providers.pncp_provider import PNCPProvider
from search.sqlite_repository import carregar_candidatos_runtime
from search.technical import (
    classificar_genericidade,
    consulta_generica,
    extrair_nucleo_semantico,
    obter_category_profile,
    parse_atributos_tecnicos,
)
from config.app_settings import MAX_RESULTADOS_REAIS, MIN_RESULTADOS_DESEJADOS, SCORE_PIPELINE_PESADO_HARD_MAX


logger = logging.getLogger("pesquisa")


def calcular_limite_candidatos_dinamico(descricao, limite_maximo):
    analise = parse_atributos_tecnicos(str(descricao or ""))
    termos = analise.get("termos_principais", [])
    atributos = analise.get("atributos_criticos", {})
    genericidade = classificar_genericidade(descricao)

    if genericidade == "alta":
        limite = 150
    elif genericidade == "media":
        limite = 300
    elif atributos:
        limite = 600
    elif len(termos) >= 6:
        limite = 600
    elif len(termos) <= 3 and not atributos:
        limite = 300
    else:
        limite = 600

    return max(120, min(int(limite_maximo), limite))


def deve_usar_criterios_locais(descricao):
    analise = parse_atributos_tecnicos(str(descricao or ""))
    termos = analise.get("termos_principais", [])
    atributos = analise.get("atributos_criticos", {})
    if atributos and 1 <= len(termos) <= 5:
        return True
    if consulta_generica(descricao) or len(termos) <= 3 or len(termos) <= 7:
        return True
    return False


def resultado_rigido_suficiente(resultados_rigido):
    pipeline = getattr(resultados_rigido, "pipeline_stats", {}) or {}
    if pipeline.get("pipeline_cache_hit") and len(resultados_rigido) >= 5:
        return True

    if (
        len(resultados_rigido) >= 10
        and pipeline.get("top_intermediario", 0) >= 90
        and pipeline.get("relevantes_intermediarios", 0) >= 10
    ):
        return True

    if len(resultados_rigido) >= MAX_RESULTADOS_REAIS:
        return True

    scores = [resultado.get("score", 0) for resultado in resultados_rigido]
    if not scores:
        return False

    top_score = max(scores)
    if sum(1 for score in scores if score >= 80) >= 20:
        return True
    if sum(1 for score in scores if score >= 90) >= 10:
        return True
    resultados_fortes = sum(1 for score in scores if score >= 70)
    if top_score >= 90 and resultados_fortes >= 8:
        return True

    return top_score >= 85 and len(resultados_rigido) >= 20


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
    nucleo_semantico = extrair_nucleo_semantico(str(descricao or ""))
    semantic_group_key = nucleo_semantico.get("grupo_semantico") or nucleo_semantico.get("semantic_core") or "sem_core"
    categoria = nucleo_semantico.get("categoria") or "generica"
    category_profile = obter_category_profile(categoria)
    rigidez_categoria = category_profile.get("rigidez", "media")
    query_genericidade = classificar_genericidade(descricao)
    tempo_ia_ms = 0
    tempo_sqlite_ms = 0
    tempo_score_ms = 0
    tempo_pncp_ms = 0
    inicio_ia = time.perf_counter()
    usar_criterios_locais = deve_usar_criterios_locais(descricao)
    if usar_criterios_locais:
        criterios = extrair_criterios_simples(descricao)
        logger.info("IA ignorada descricao=%r motivo=criterios_locais_suficientes", descricao)
    else:
        criterios = extrair_criterios_com_ia(descricao)
    tempo_ia_ms = round((time.perf_counter() - inicio_ia) * 1000, 2)
    candidatos = []
    resultados_rigido = []
    resultados_relaxado = []
    resultados_amplo = []
    sqlite_search = {}

    if "licitacon" in fontes:
        inicio_sqlite = time.perf_counter()
        limite_candidatos = calcular_limite_candidatos_dinamico(descricao, limite)
        candidatos = carregar_candidatos_runtime(
            descricao_busca=descricao,
            criterios=criterios,
            limite=limite_candidatos,
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
        top_rigido = max([r.get("score", 0) for r in resultados_rigido] or [0])
        relevantes_rigidos = sum(1 for r in resultados_rigido if r.get("score", 0) >= 45)
        abortar_expansao = (
            rigidez_categoria == "alta"
            and len(resultados_rigido) < 5
            and top_rigido < 35
        )
        rigido_suficiente = resultado_rigido_suficiente(resultados_rigido)

        if abortar_expansao:
            logger.info(
                "[expansao_hard_abort] descricao=%r categoria=%s motivo_aborto=baixa_aderencia top_score=%s candidatos_relevantes=%s",
                descricao,
                categoria,
                top_rigido,
                relevantes_rigidos,
            )
        elif len(resultados_rigido) < 5 and top_rigido < 35:
            logger.info(
                "[expansao_soft_penalty] descricao=%r categoria=%s rigidez=%s motivo=baixa_aderencia top_score=%s candidatos_relevantes=%s acao=continuar_expansao",
                descricao,
                categoria,
                rigidez_categoria,
                top_rigido,
                relevantes_rigidos,
            )
        elif rigido_suficiente:
            logger.info(
                "[early_stop] motivo=alta_confianca descricao=%r top_score=%s resultados_rigidos=%s",
                descricao,
                top_rigido,
                len(resultados_rigido),
            )
        else:
            score_pesado_usado = getattr(resultados_rigido, "pipeline_stats", {}).get("score_pesado_real", 0)
            score_pesado_restante = max(0, SCORE_PIPELINE_PESADO_HARD_MAX - score_pesado_usado)
            if score_pesado_restante > 0:
                resultados_relaxado = buscar_item(
                    candidatos,
                    descricao,
                    qtd_min,
                    qtd_max,
                    criterios,
                    modo="relaxado",
                    exigir_homologacao=True,
                    max_score_pesado=score_pesado_restante,
                )
                score_pesado_usado += getattr(resultados_relaxado, "pipeline_stats", {}).get("score_pesado_real", 0)

            score_pesado_restante = max(0, SCORE_PIPELINE_PESADO_HARD_MAX - score_pesado_usado)
            if score_pesado_restante > 0 and (
                rigidez_categoria != "alta"
                or not consulta_generica(descricao)
                or top_rigido >= 45
            ):
                resultados_amplo = buscar_item(
                    candidatos,
                    descricao,
                    qtd_min,
                    qtd_max,
                    criterios,
                    modo="amplo",
                    exigir_homologacao=True,
                    max_score_pesado=score_pesado_restante,
                )
        tempo_score_ms = round((time.perf_counter() - inicio_score) * 1000, 2)
    score_pipeline = [
        getattr(resultados_rigido, "pipeline_stats", {}),
        getattr(resultados_relaxado, "pipeline_stats", {}),
        getattr(resultados_amplo, "pipeline_stats", {}),
    ]
    registros_score_pesado = sum(
        stats.get("score_pesado_real", stats.get("score_pesado", 0))
        for stats in score_pipeline
    )
    resultados = juntar_resultados(
        resultados_rigido,
        resultados_relaxado,
        resultados_amplo,
    )
    resultados_apos_juncao = len(resultados)
    if rigidez_categoria == "alta":
        score_minimo_final = max(35, int(category_profile.get("score_minimo", 35)))
    else:
        score_minimo_final = min(35, int(category_profile.get("score_minimo", 35)))
    logger.info(
        "[filtro_final_categoria] descricao=%r categoria=%s rigidez=%s score_minimo=%s resultados_antes=%s",
        descricao,
        categoria,
        rigidez_categoria,
        score_minimo_final,
        len(resultados),
    )
    resultados_filtrados = []
    descartes_finais = {}
    for resultado in resultados:
        score_resultado = resultado.get("score", 0)
        score_minimo_resultado = score_minimo_final
        if resultado.get("critico_ausente_soft"):
            score_minimo_resultado = max(35, score_minimo_final - 25)
        if score_resultado >= score_minimo_resultado:
            resultados_filtrados.append(resultado)
            continue
        descartes_finais["score_minimo_final"] = descartes_finais.get("score_minimo_final", 0) + 1
        logger.info(
            "[candidato_descartado] motivo=score_minimo_final categoria=%s score=%s descricao=%r extra=%s",
            categoria,
            round(score_resultado, 2) if isinstance(score_resultado, (int, float)) else score_resultado,
            resultado.get("descricao", ""),
            {
                "etapa": "service_filtro_final",
                "score_minimo": score_minimo_resultado,
                "rigidez": rigidez_categoria,
                "critico_ausente_soft": bool(resultado.get("critico_ausente_soft")),
                "atributo_critico_ausente": resultado.get("atributo_critico_ausente", ""),
            },
        )
    resultados = resultados_filtrados[:MAX_RESULTADOS_REAIS]
    logger.info(
        "[funil_pipeline] origem=service categoria=%s rigidez=%s fts=%s apos_pre=%s apos_intermediario=%s apos_score=%s apos_hard_divergence=%s apos_aderencia=%s resultado_final=%s apos_juncao=%s descartes=%s",
        categoria,
        rigidez_categoria,
        len(candidatos),
        next((stats.get("apos_pre_filtro", 0) for stats in score_pipeline if stats), 0),
        next((stats.get("apos_intermediario", 0) for stats in score_pipeline if stats), 0),
        sum((stats.get("funil_pipeline") or {}).get("apos_score", stats.get("score_pesado_real", 0)) for stats in score_pipeline if stats),
        sum((stats.get("funil_pipeline") or {}).get("apos_hard_divergence", 0) for stats in score_pipeline if stats),
        sum((stats.get("funil_pipeline") or {}).get("apos_aderencia", 0) for stats in score_pipeline if stats),
        len(resultados),
        resultados_apos_juncao,
        descartes_finais,
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
        "limite_candidatos": len(candidatos) if "licitacon" not in fontes else locals().get("limite_candidatos", limite),
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
        "registros_processados": registros_score_pesado + len(resultados_pncp),
        "score_pesado_real": registros_score_pesado,
        "candidatos_recuperados": len(candidatos),
        "score_pipeline": score_pipeline,
        "pncp_pipeline": pncp_stats,
        "score_max": max(scores) if scores else 0,
        "score_min": min(scores) if scores else 0,
        "fontes": fontes,
        "criterios_locais": usar_criterios_locais,
        "semantic_group_key": semantic_group_key,
        "query_genericidade": query_genericidade,
    }

    pipeline_resumo = score_pipeline[0] if score_pipeline else {}
    logger.info(
        "[pipeline] grupo_semantico=%r query_genericidade=%s candidatos_fts=%s apos_pre=%s apos_intermediario=%s score_pesado=%s resultados_finais=%s early_stop=%s cache_hit=%s tempo_total_ms=%s motivo_aborto=%s motivo_truncamento=%s",
        semantic_group_key,
        query_genericidade,
        len(candidatos),
        pipeline_resumo.get("apos_pre_filtro", 0),
        pipeline_resumo.get("apos_intermediario", 0),
        estatisticas["score_pesado_real"],
        len(resultados),
        any(stats.get("early_stop") for stats in score_pipeline),
        any(stats.get("pipeline_cache_hit") or stats.get("ranking_cache_hit") for stats in score_pipeline),
        tempo_total_ms,
        next((stats.get("motivo_aborto") for stats in score_pipeline if stats.get("motivo_aborto")), ""),
        "max_resultados_finais" if len(resultados) >= MAX_RESULTADOS_REAIS else "",
    )

    logger.info(
        "Pesquisa item descricao_original=%r descricao_resumida=%r fontes=%s resultados=%s score_max=%s score_min=%s candidatos=%s limite_candidatos=%s tempo_total_ms=%s tempo_sqlite_ms=%s tempo_pncp_ms=%s tempo_ia_ms=%s tempo_score_ms=%s registros_processados=%s score_pesado_real=%s sqlite=%s",
        descricao,
        criterios.get("descricao_resumida", descricao),
        fontes,
        len(resultados),
        estatisticas["score_max"],
        estatisticas["score_min"],
        len(candidatos),
        estatisticas["limite_candidatos"],
        tempo_total_ms,
        tempo_sqlite_ms,
        tempo_pncp_ms,
        tempo_ia_ms,
        tempo_score_ms,
        estatisticas["registros_processados"],
        estatisticas["score_pesado_real"],
        estatisticas["sqlite_search"],
    )
    return criterios, resultados, estatisticas
