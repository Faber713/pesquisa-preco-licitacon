from search.statistics import (
    ELEVADO,
    INCOMPATIVEL,
    INEXEQUIVEL,
    SUSPEITO,
    VALIDO,
    classificar_resultados,
)


def classificar_precos(resultados):
    return classificar_resultados(resultados)


def gerar_justificativa_automatica(fontes, total_precos=0, estatisticas=None):
    estatisticas = estatisticas or {}
    fontes_norm = " ".join(str(f or "").lower() for f in fontes)
    usa_dominio_amplo = any(
        termo in fontes_norm
        for termo in ["internet", "fornecedor", "dominio amplo", "mercado"]
    )
    usa_publica = any(termo in fontes_norm for termo in ["pncp", "licitacon", "compras.gov", "tce"])
    poucos_precos = total_precos < 3
    alta_variacao = (estatisticas.get("coeficiente_variacao") or 0) > 25

    partes = [
        "A pesquisa de precos considerou fontes publicas e registros homologados compativeis com o objeto descrito, observando similaridade textual, categoria do item, contexto tecnico, quantitativo e recencia."
    ]
    if usa_publica:
        partes.append("Foram priorizadas bases oficiais, como PNCP, Compras.gov e LicitaCon/TCE, pela maior rastreabilidade juridica e administrativa.")
    if usa_dominio_amplo or poucos_precos:
        partes.append(
            "Considerando a baixa disponibilidade de precos homologados plenamente compativeis ou a necessidade de refletir valores praticados atualmente no mercado, foram admitidos complementarmente precos de sitios eletronicos ou fornecedores, nos termos da IN SEGES no 65/2021, sem dispensa da validacao tecnica pelo servidor."
        )
    if alta_variacao:
        partes.append("A amostra apresentou dispersao relevante, motivo pelo qual os valores classificados como inexequiveis, elevados ou suspeitos foram mantidos apenas como alerta para decisao motivada.")
    return " ".join(partes)
