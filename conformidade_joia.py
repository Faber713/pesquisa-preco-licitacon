from datetime import date, datetime
from statistics import mean, median

from util import converter_numero


PRAZO_MESES_PRECO_PUBLICO = 6
DIAS_PRAZO_PRECO_PUBLICO = 183
MINIMO_PRECOS_REGRA_GERAL = 3


def _parse_data(valor):
    if valor is None:
        return None

    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return None

    formatos = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]

    for formato in formatos:
        try:
            return datetime.strptime(texto[:19], formato).date()
        except ValueError:
            pass

    return None


def _percentil_ordenado(valores, proporcao):
    if not valores:
        return None

    posicao = (len(valores) - 1) * proporcao
    inferior = int(posicao)
    superior = min(inferior + 1, len(valores) - 1)
    peso = posicao - inferior
    return valores[inferior] * (1 - peso) + valores[superior] * peso


def _classificar_precos(valores):
    if len(valores) < 4:
        return valores, []

    ordenados = sorted(valores)
    q1 = _percentil_ordenado(ordenados, 0.25)
    q3 = _percentil_ordenado(ordenados, 0.75)
    intervalo = q3 - q1

    if intervalo <= 0:
        return valores, []

    limite_inferior = q1 - 1.5 * intervalo
    limite_superior = q3 + 1.5 * intervalo

    aproveitados = [
        valor for valor in valores
        if limite_inferior <= valor <= limite_superior
    ]
    descartados = [
        valor for valor in valores
        if valor < limite_inferior or valor > limite_superior
    ]

    return aproveitados, descartados


def avaliar_conformidade_pesquisa(resultados, data_pesquisa=None):
    if data_pesquisa is None:
        data_pesquisa = date.today()

    precos = []
    precos_no_prazo = []

    for resultado in resultados:
        valor = converter_numero(resultado.get("valor_unitario"))
        if valor is None or valor <= 0:
            continue

        precos.append(valor)

        data_referencia = (
            _parse_data(resultado.get("data_homologacao"))
            or _parse_data(resultado.get("data"))
        )
        if data_referencia is not None:
            dias = (data_pesquisa - data_referencia).days
            if 0 <= dias <= DIAS_PRAZO_PRECO_PUBLICO:
                precos_no_prazo.append(valor)

    precos_aproveitados, precos_descartados = _classificar_precos(precos)

    estatisticas = {
        "total_precos": len(precos),
        "precos_no_prazo_6_meses": len(precos_no_prazo),
        "precos_aproveitados": len(precos_aproveitados),
        "precos_descartados": len(precos_descartados),
        "media": None,
        "mediana": None,
        "menor": None,
        "maior": None,
        "metodo_sugerido": "",
        "valor_sugerido": None,
        "alertas": [],
    }

    if precos_aproveitados:
        estatisticas["media"] = mean(precos_aproveitados)
        estatisticas["mediana"] = median(precos_aproveitados)
        estatisticas["menor"] = min(precos_aproveitados)
        estatisticas["maior"] = max(precos_aproveitados)

        if len(precos_aproveitados) >= MINIMO_PRECOS_REGRA_GERAL:
            amplitude = estatisticas["maior"] - estatisticas["menor"]
            variacao_relativa = amplitude / estatisticas["mediana"] if estatisticas["mediana"] else 0

            if variacao_relativa > 0.25:
                estatisticas["metodo_sugerido"] = "mediana"
                estatisticas["valor_sugerido"] = estatisticas["mediana"]
            else:
                estatisticas["metodo_sugerido"] = "media"
                estatisticas["valor_sugerido"] = estatisticas["media"]
        else:
            estatisticas["metodo_sugerido"] = "menor preco disponivel, com justificativa"
            estatisticas["valor_sugerido"] = estatisticas["menor"]

    if len(precos) < MINIMO_PRECOS_REGRA_GERAL:
        estatisticas["alertas"].append(
            "A regra geral exige calculo sobre tres ou mais precos; usar menos exige justificativa no processo."
        )

    if len(precos_no_prazo) < MINIMO_PRECOS_REGRA_GERAL:
        estatisticas["alertas"].append(
            "Ha menos de tres precos dentro do prazo de 6 meses previsto para contratacoes similares no LicitaCon."
        )

    if precos_descartados:
        estatisticas["alertas"].append(
            "Foram identificados valores fora da faixa estatistica; a desconsideracao precisa ser justificada."
        )

    return estatisticas


def formatar_moeda(valor):
    if valor is None:
        return "-"

    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
