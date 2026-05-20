import logging
import time

from config.runtime_settings import SEARCH_MIN_RESULTS_BEFORE_EXPANSION
from search.busca import buscar_item, juntar_resultados
from search.providers.base_provider import BaseProvider
from search.sqlite_repository import carregar_candidatos_runtime


logger = logging.getLogger("provider.licitacon")


class LicitaConProvider(BaseProvider):
    nome = "licitacon"
    confiabilidade = 1.00

    def buscar(
        self,
        descricao,
        *,
        criterios,
        qtd_min,
        qtd_max,
        limite,
        search_db_mode,
        raw_path,
        operational_path,
        estrategia_busca="inteligente",
    ):
        inicio = time.perf_counter()
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
        score_stats = {
            "candidatos": 0,
            "descartados": 0,
            "score_pesado": 0,
            "resultados_finais": 0,
        }
        resultados_rigido = buscar_item(
            candidatos,
            descricao,
            qtd_min,
            qtd_max,
            criterios,
            modo="rigido",
            exigir_homologacao=True,
            stats=score_stats,
        )
        estrategia_busca = str(estrategia_busca or "inteligente").lower()
        resultados_relaxado = []
        resultados_amplo = []
        executar_relaxado = (
            estrategia_busca == "ampla"
            or (
                estrategia_busca == "inteligente"
                and len(resultados_rigido) < SEARCH_MIN_RESULTS_BEFORE_EXPANSION
            )
        )
        if executar_relaxado:
            resultados_relaxado = buscar_item(
                candidatos,
                descricao,
                qtd_min,
                qtd_max,
                criterios,
                modo="relaxado",
                exigir_homologacao=True,
                stats=score_stats,
            )
        executar_amplo = (
            estrategia_busca == "ampla"
            or (
                estrategia_busca == "inteligente"
                and len(resultados_rigido) + len(resultados_relaxado) < SEARCH_MIN_RESULTS_BEFORE_EXPANSION
            )
        )
        if executar_amplo:
            resultados_amplo = buscar_item(
                candidatos,
                descricao,
                qtd_min,
                qtd_max,
                criterios,
                modo="amplo",
                exigir_homologacao=True,
                stats=score_stats,
            )
        resultados = juntar_resultados(
            resultados_rigido,
            resultados_relaxado,
            resultados_amplo,
        )
        stats = {
            "candidatos": len(candidatos),
            "rigido": len(resultados_rigido),
            "relaxado": len(resultados_relaxado),
            "amplo": len(resultados_amplo),
            "sqlite_search": sqlite_search,
            "score_stats": score_stats,
            "estrategia_busca": estrategia_busca,
            "tempo_ms": round((time.perf_counter() - inicio) * 1000, 2),
        }
        logger.debug(
            "[provider_end] provider=licitacon descricao=%r candidatos=%s descartados=%s score_pesado=%s resultados=%s tempo_ms=%s",
            descricao,
            stats["candidatos"],
            score_stats["descartados"],
            score_stats["score_pesado"],
            len(resultados),
            stats["tempo_ms"],
        )
        return resultados, stats
