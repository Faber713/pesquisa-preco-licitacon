from datetime import datetime

from search.price_validation import gerar_justificativa_automatica
from web.services.cesta_service import agrupar_cesta_por_item, obter_cesta, resumo_cesta


def _metodologia_label(valor):
    return {
        "mediana": "Mediana",
        "media": "Media simples",
        "menor_preco": "Menor preco",
        "combinado": "Combinado",
    }.get(valor or "", valor or "-")


def _separar_precos(precos):
    considerados = []
    desconsiderados = []
    for preco in precos:
        if preco.get("considerar", True):
            considerados.append(preco)
        else:
            desconsiderados.append(preco)
    return considerados, desconsiderados


def gerar_dossie_contexto(*, servidor_responsavel="", filtros=None):
    cesta = obter_cesta()
    grupos = agrupar_cesta_por_item(cesta)
    itens = []

    for indice, grupo in enumerate(grupos, start=1):
        considerados, desconsiderados = _separar_precos(grupo["precos"])
        resumo = dict(grupo["resumo"])
        resumo["metodologia_label"] = _metodologia_label(resumo.get("metodologia_formacao_preco"))
        fontes_item = [preco.get("fonte", "") for preco in grupo["precos"]]
        justificativa = gerar_justificativa_automatica(
            fontes_item,
            total_precos=len(considerados),
            estatisticas=resumo,
        )
        itens.append({
            "numero": grupo.get("numero") or indice,
            "descricao": grupo.get("descricao"),
            "quantidade": grupo.get("quantidade"),
            "status": grupo.get("status"),
            "resultados_alvo": grupo.get("resultados_alvo"),
            "total_precos": grupo.get("total"),
            "considerados_qtd": len(considerados),
            "desconsiderados_qtd": len(desconsiderados),
            "resumo": resumo,
            "justificativa_automatica": justificativa,
            "precos_considerados": considerados,
            "precos_desconsiderados": desconsiderados,
            "evidencias": [preco.get("evidencia_web") for preco in grupo["precos"] if preco.get("evidencia_web")],
        })

    resumo = resumo_cesta(cesta)
    fontes = sorted({
        preco.get("fonte", "LicitaCon RS") or "LicitaCon RS"
        for item in itens
        for preco in item["precos_considerados"] + item["precos_desconsiderados"]
    })

    return {
        "gerado_em": datetime.now(),
        "orgao": "Prefeitura Municipal de Joia/RS",
        "titulo": "Dossie de Pesquisa de Precos",
        "servidor_responsavel": servidor_responsavel or "Nao informado",
        "metodologia_global": _metodologia_label(resumo.get("metodologia_formacao_preco")),
        "fontes_utilizadas": fontes or ["LicitaCon RS"],
        "filtros": filtros or {
            "periodo": "Conforme filtros utilizados na pesquisa",
            "exclusao_orgao_origem": "Conforme selecao realizada na pesquisa",
            "tolerancia_percentual": "Conforme parametros da pesquisa",
            "limite_resultados": "Conforme parametros da pesquisa",
        },
        "resumo": resumo,
        "justificativa_automatica": gerar_justificativa_automatica(
            fontes,
            total_precos=resumo.get("considerados", 0),
            estatisticas=resumo,
        ),
        "itens": itens,
    }
