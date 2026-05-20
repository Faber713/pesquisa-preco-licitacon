import logging
import statistics as py_statistics

from utils.util import converter_numero


logger = logging.getLogger("pesquisa.statistics")

VALIDO = "VALIDO"
INEXEQUIVEL = "INEXEQUIVEL"
ELEVADO = "EXCESSIVAMENTE ELEVADO"
SUSPEITO = "SUSPEITO"
INCOMPATIVEL = "INCOMPATIVEL"


def valor_resultado(resultado):
    return converter_numero(resultado.get("valor_unitario") or resultado.get("valor"))


def calcular_estatisticas_precos(resultados):
    valores = [valor for valor in (valor_resultado(r) for r in resultados) if valor and valor > 0]
    if not valores:
        return {
            "media": None,
            "mediana": None,
            "desvio_padrao": None,
            "coeficiente_variacao": None,
            "menor": None,
            "maior": None,
            "qtd": 0,
            "outliers": [],
        }

    media = py_statistics.mean(valores)
    mediana = py_statistics.median(valores)
    desvio = py_statistics.pstdev(valores) if len(valores) > 1 else 0
    coeficiente = (desvio / media * 100) if media else 0
    limite_desvio = max(desvio * 2, mediana * 0.30)
    outliers = [
        valor
        for valor in valores
        if len(valores) >= 4 and abs(valor - mediana) > limite_desvio
    ]
    stats = {
        "media": round(media, 2),
        "mediana": round(mediana, 2),
        "desvio_padrao": round(desvio, 2),
        "coeficiente_variacao": round(coeficiente, 2),
        "menor": round(min(valores), 2),
        "maior": round(max(valores), 2),
        "qtd": len(valores),
        "outliers": [round(v, 2) for v in outliers],
    }
    logger.debug(
        "[score_statistics] qtd=%s media=%s mediana=%s desvio=%s cv=%s outliers=%s",
        stats["qtd"],
        stats["media"],
        stats["mediana"],
        stats["desvio_padrao"],
        stats["coeficiente_variacao"],
        len(stats["outliers"]),
    )
    return stats


def classificar_preco(valor, estatisticas):
    valor = converter_numero(valor)
    if not valor or valor <= 0:
        return SUSPEITO, ["Valor ausente ou invalido."]

    mediana = estatisticas.get("mediana")
    desvio = estatisticas.get("desvio_padrao") or 0
    cv = estatisticas.get("coeficiente_variacao") or 0
    qtd = estatisticas.get("qtd") or 0
    if not mediana or qtd < 2:
        return VALIDO, []

    faixa_minima = 0.30 if cv <= 25 else 0.40
    faixa_maxima = 0.30 if cv <= 25 else 0.45
    margem_desvio = desvio * (1.8 if cv <= 25 else 2.3)
    limite_baixo = min(mediana * (1 - faixa_minima), mediana - margem_desvio)
    limite_alto = max(mediana * (1 + faixa_maxima), mediana + margem_desvio)

    if valor < limite_baixo:
        return INEXEQUIVEL, ["Valor abaixo da faixa contextual calculada pela mediana e dispersao."]
    if valor > limite_alto:
        return ELEVADO, ["Valor acima da faixa contextual calculada pela mediana e dispersao."]
    if cv > 35 and abs(valor - mediana) > mediana * 0.25:
        return SUSPEITO, ["Amostra com alta dispersao; valor requer validacao tecnica."]
    return VALIDO, []


def classificar_resultados(resultados):
    estatisticas = calcular_estatisticas_precos(resultados)
    for resultado in resultados:
        if resultado.get("item_descartado") or resultado.get("compatibilidade_status") == INCOMPATIVEL:
            status = INCOMPATIVEL
            alertas = ["Resultado marcado como incompatível pelo filtro semantico."]
        else:
            status, alertas = classificar_preco(valor_resultado(resultado), estatisticas)
        existentes = list(resultado.get("alertas_preco") or [])
        resultado["status_validacao"] = status
        if existentes and status == VALIDO:
            resultado["status_validacao"] = SUSPEITO
        resultado["alertas_preco"] = list(dict.fromkeys(existentes + alertas))
        resultado["motivos_alerta"] = " | ".join(resultado["alertas_preco"])
        logger.debug(
            "[classificacao_preco] status=%s valor=%s score=%s descricao=%r",
            status,
            valor_resultado(resultado),
            resultado.get("score"),
            str(resultado.get("descricao", ""))[:140],
        )
    return resultados, estatisticas
