import logging
import time

from ia.ia_criterios import extrair_criterios_com_ia
from search.busca import buscar_item, juntar_resultados
from search.sqlite_repository import carregar_candidatos_runtime
from utils.config import MIN_RESULTADOS_DESEJADOS


logger = logging.getLogger(__name__)


def executar_pesquisa_item(
    descricao,
    qtd_min,
    qtd_max,
    *,
    limite,
    search_db_mode,
    raw_path,
    operational_path,
):
    inicio = time.perf_counter()
    criterios = extrair_criterios_com_ia(descricao)
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
    resultados = juntar_resultados(
        resultados_rigido,
        resultados_relaxado,
        resultados_amplo,
    )

    tempo_total_ms = round((time.perf_counter() - inicio) * 1000, 2)
    estatisticas = {
        "candidatos": len(candidatos),
        "rigido": len(resultados_rigido),
        "relaxado": len(resultados_relaxado),
        "amplo": len(resultados_amplo),
        "total": len(resultados),
        "minimo_desejado": MIN_RESULTADOS_DESEJADOS,
        "sqlite_search": candidatos.attrs.get("sqlite_search", {}),
        "tempo_total_ms": tempo_total_ms,
    }

    logger.info(
        "Pesquisa item concluida descricao=%r resultados=%s candidatos=%s tempo_ms=%s sqlite=%s",
        descricao,
        len(resultados),
        len(candidatos),
        tempo_total_ms,
        estatisticas["sqlite_search"],
    )
    return criterios, resultados, estatisticas
