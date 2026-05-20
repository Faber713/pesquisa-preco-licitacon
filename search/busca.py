import logging

from config.runtime_settings import SEARCH_MAX_SCORE_CANDIDATES
from config.app_settings import (
    LIMIAR_RIGIDO,
    LIMIAR_RELAXADO,
    LIMIAR_AMPLO,
    MIN_PCT_OBRIGATORIOS_RIGIDO,
    MIN_PCT_OBRIGATORIOS_RELAXADO,
    MIN_PCT_OBRIGATORIOS_AMPLO,
    LIMIAR_RELAXADO_SEM_QTD,
    LIMIAR_AMPLO_SEM_QTD
)

from ia.regras_tecnicas import validar_regras_tecnicas
from ia.regras_produtos_eletricos import validar_produto_eletrico
from utils.util import pegar_coluna, converter_numero, palavras_fortes, termos_compativeis, normalizar
from search.score import calcular_score
from search.intelligence import (
    calcular_score_final_inteligente,
    quantity_similarity_score,
    quantidade_desejada,
    recency_score,
    semantic_category_match,
    source_priority_score,
)
from search.critical_specs import validar_especificacao_critica


logger = logging.getLogger("pesquisa.busca")


def _incrementar_stats(stats, chave, valor=1):
    if stats is not None:
        stats[chave] = stats.get(chave, 0) + valor


def _score_preliminar(descricao_usada, descricao_resultado, criterios, modo):
    resultado_norm = normalizar(descricao_resultado)
    termos = []
    termos.extend(criterios.get("termos_obrigatorios", []) or [])
    if modo != "rigido":
        termos.extend(criterios.get("termos_importantes", []) or [])
    termos = list(dict.fromkeys([normalizar(termo) for termo in termos if normalizar(termo)]))
    if not termos:
        fortes = palavras_fortes(descricao_usada)
        termos = fortes[:6]
    if not termos:
        return 1
    encontrados = sum(1 for termo in termos if termos_compativeis(termo, resultado_norm))
    if encontrados == 0:
        return 0
    return encontrados / len(termos)


# ============================================================
# VALIDAÇÕES DE DADOS HOMOLOGADOS
# ============================================================

def obter_valor_unitario(row):
    return pegar_coluna(row, [
        "Vl. Un. Homolog.",
        "Vl. Un. Homolog",
        "Vl. Un. Homolg.",
        "Vl. Un. Homolg",
        "Valor Unitário",
        "Valor Unitario",
        "Valor Unitário Homologado",
        "Valor Unitario Homologado",
        "Vl Unit Homolog",
        "Vl Unit Homolog.",
        "Vl. Unit. Homolog.",
        "Vl. Unit. Homolog"
    ])


def obter_valor_total(row):
    return pegar_coluna(row, [
        "Vl. Total Homolog.",
        "Vl. Total Homolog",
        "Vl. Total Homolg.",
        "Vl. Total Homolg",
        "Valor Total",
        "Valor Total Homologado"
    ])


def obter_vencedor(row):
    return pegar_coluna(row, [
        "Vencedor",
        "Fornecedor",
        "Fornecedor Vencedor",
        "Empresa Vencedora",
        "Razão Social",
        "Razao Social",
        "Nome Vencedor",
        "Credor"
    ])


def tem_valor_homologado(valor_unitario):
    valor = converter_numero(valor_unitario)

    if valor is None:
        return False

    if valor <= 0:
        return False

    return True


def tem_vencedor_homologado(vencedor):
    if vencedor is None:
        return False

    texto = str(vencedor).strip()

    if not texto:
        return False

    if texto.lower() in {"nan", "none", "null", "-", "--"}:
        return False

    return True


def registro_tem_homologacao_valida(row):
    valor_unitario = obter_valor_unitario(row)
    vencedor = obter_vencedor(row)

    return (
        tem_valor_homologado(valor_unitario)
        and tem_vencedor_homologado(vencedor)
    )


def validar_aderencia_produto(descricao_busca, descricao_resultado):
    ok_eletrico, _motivo_eletrico = validar_produto_eletrico(
        descricao_busca,
        descricao_resultado
    )

    if not ok_eletrico:
        return False, []

    fortes_busca = palavras_fortes(descricao_busca)
    busca_norm = normalizar(descricao_busca)
    resultado_norm = normalizar(descricao_resultado)
    primeira_palavra_resultado = resultado_norm.split()[0] if resultado_norm.split() else ""
    inicio_resultado = " ".join(resultado_norm.split()[:12])
    inicio_curto_resultado = " ".join(resultado_norm.split()[:5])

    if not fortes_busca:
        return True, []

    encontrados = [
        termo for termo in fortes_busca
        if termos_compativeis(termo, resultado_norm)
    ]

    if encontrados:
        busca_timer = "timer" in busca_norm or "temporizador" in busca_norm

        if busca_timer:
            nucleo_timer_no_inicio = any(
                termo in inicio_resultado
                for termo in [
                    "timer",
                    "temporizador",
                    "programador",
                    "rele temporizador",
                    "relogio temporizador",
                ]
            )

            if not nucleo_timer_no_inicio:
                return False, encontrados

        encontrados_no_inicio = [
            termo for termo in encontrados
            if termos_compativeis(termo, inicio_resultado)
        ]
        encontrados_no_inicio_curto = [
            termo for termo in encontrados
            if termos_compativeis(termo, inicio_curto_resultado)
        ]

        produtos_principais_incompativeis = {
            "ar", "condicionado", "split", "compressor", "motor", "bomba",
            "maquina", "equipamento", "aparelho", "cadeira", "veiculo",
            "trator", "rolo", "kit", "painel", "quadro", "sistema",
            "conjunto", "bebedouro", "geladeira", "freezer", "fogao",
            "forno", "microondas", "impressora", "notebook", "computador",
            "tv", "televisor", "televisao", "telefone", "celular",
            "smartphone", "tablet", "radio", "camera", "cronometro",
            "relogio", "fotopolimerizador", "concentrador", "oxigenio",
            "nebulizador", "monitor", "autoclave", "seladora", "jogo",
            "fritadeira", "airfryer", "torneira", "secadora"
        }

        if (
            busca_timer
            and primeira_palavra_resultado in produtos_principais_incompativeis
        ):
            return False, encontrados

        palavras_inicio = set(inicio_resultado.split())

        if (
            not encontrados_no_inicio
            and palavras_inicio.intersection(produtos_principais_incompativeis)
        ):
            return False, encontrados

        if (
            not encontrados_no_inicio_curto
            and palavras_inicio.intersection(produtos_principais_incompativeis)
        ):
            return False, encontrados

        return True, encontrados

    return False, encontrados


# ============================================================
# BUSCA
# ============================================================

def buscar_item(
    df,
    descricao_busca,
    qtd_min,
    qtd_max,
    criterios,
    modo="rigido",
    ignorar_quantidade=False,
    exigir_homologacao=True,
    stats=None,
):
    resultados = []

    if modo == "rigido":
        limiar = LIMIAR_RIGIDO
        min_pct_obrigatorios = MIN_PCT_OBRIGATORIOS_RIGIDO
        descricao_usada = descricao_busca

    elif modo == "relaxado":
        limiar = LIMIAR_RELAXADO
        min_pct_obrigatorios = MIN_PCT_OBRIGATORIOS_RELAXADO
        descricao_usada = descricao_busca

    elif modo == "amplo":
        limiar = LIMIAR_AMPLO
        min_pct_obrigatorios = MIN_PCT_OBRIGATORIOS_AMPLO
        descricao_usada = criterios.get("descricao_sugerida_licitacon", descricao_busca)

    else:
        limiar = LIMIAR_RELAXADO
        min_pct_obrigatorios = MIN_PCT_OBRIGATORIOS_RELAXADO
        descricao_usada = descricao_busca

    pre_candidatos = []

    for index, row in df.iterrows():
        _incrementar_stats(stats, "candidatos")

        if exigir_homologacao and not registro_tem_homologacao_valida(row):
            _incrementar_stats(stats, "descartados")
            continue

        descricao = pegar_coluna(row, ["Item", "item", "ITEM", "Descrição", "Descricao"])
        if not descricao:
            _incrementar_stats(stats, "descartados")
            continue

        qtd_raw = pegar_coluna(row, ["Qtd.", "Qtd", "Quantidade", "QUANTIDADE"])
        qtd = converter_numero(qtd_raw)

        if qtd is None:
            _incrementar_stats(stats, "descartados")
            continue

        quantidade_fora = not (qtd_min <= qtd <= qtd_max)

        categoria = semantic_category_match(descricao_busca, descricao, criterios)
        if not categoria["ok"]:
            _incrementar_stats(stats, "descartados")
            if logger.isEnabledFor(logging.DEBUG):
                for motivo in categoria.get("rejection_reasons", []):
                    logger.debug("[rejection_reason] motivo=%s descricao=%r", motivo, descricao)
            continue

        especificacao = validar_especificacao_critica(
            descricao_busca,
            descricao,
            categoria.get("categoria_detectada") or criterios.get("categoria", ""),
        )

        preliminar = _score_preliminar(descricao_usada, descricao, criterios, modo)
        if preliminar <= 0:
            _incrementar_stats(stats, "descartados")
            continue
        if not especificacao["ok"]:
            preliminar *= 0.25
        pre_candidatos.append((preliminar, index, row, descricao, qtd_raw, qtd, quantidade_fora, categoria, especificacao))

    pre_candidatos = sorted(pre_candidatos, key=lambda item: item[0], reverse=True)
    pre_candidatos = pre_candidatos[:max(1, SEARCH_MAX_SCORE_CANDIDATES)]

    for _preliminar, index, row, descricao, qtd_raw, qtd, quantidade_fora, categoria, especificacao in pre_candidatos:
        _incrementar_stats(stats, "score_pesado")

        analise = calcular_score(descricao_usada, descricao, criterios, modo=modo)

        unidade_resultado = pegar_coluna(row, ["Un.", "Un", "Unidade"])

        regras = validar_regras_tecnicas(
            descricao_busca=descricao_busca,
            descricao_resultado=descricao,
            unidade_busca=None,
            unidade_resultado=unidade_resultado
        )

        if not regras["ok"]:
            _incrementar_stats(stats, "descartados")
            continue

        aderente, termos_fortes_encontrados = validar_aderencia_produto(
            descricao_busca,
            descricao
        )

        if not aderente:
            _incrementar_stats(stats, "descartados")
            continue

        score_tecnico = max(0, 100 - regras["penalidade"])
        analise["score"] = max(0, analise["score"] - regras["penalidade"])

        if ignorar_quantidade and quantidade_fora:
            if modo == "relaxado" and analise["score"] < LIMIAR_RELAXADO_SEM_QTD:
                continue
            if modo == "amplo" and analise["score"] < LIMIAR_AMPLO_SEM_QTD:
                continue

        if modo == "rigido":
            if analise["pct_obrigatorios"] < (min_pct_obrigatorios * 100):
                _incrementar_stats(stats, "descartados")
                continue

        if analise["score"] >= limiar:
            valor_unitario = obter_valor_unitario(row)
            valor_total = obter_valor_total(row)
            vencedor = obter_vencedor(row)
            alvo_qtd = quantidade_desejada(qtd_min, qtd_max, criterios)
            score_quantidade = quantity_similarity_score(qtd, alvo_qtd)
            fonte_base = pegar_coluna(row, ["Fonte Base"]) or "LicitaCon RS"
            data_ref = pegar_coluna(row, ["Data Homologacao"]) or pegar_coluna(row, ["Abertura"])
            ano_ref = pegar_coluna(row, ["Ano"])
            score_recencia = recency_score(data_ref, ano_ref)
            score_fonte = source_priority_score(fonte_base)
            score_final = calcular_score_final_inteligente(
                score_textual=analise["score"],
                score_categoria=categoria["score"],
                score_quantidade=score_quantidade,
                score_tecnico=score_tecnico,
                score_recencia=score_recencia,
                score_fonte=score_fonte,
            )
            alertas_preco = []
            if not especificacao["ok"]:
                score_final = max(0, score_final - 35)
                alertas_preco.extend(f"SUSPEITO: {motivo}" for motivo in especificacao.get("motivos", []))
            compatibility_reasons = list(categoria.get("compatibility_reasons") or [])
            if termos_fortes_encontrados:
                compatibility_reasons.append("termos fortes encontrados")
            if score_quantidade >= 70:
                compatibility_reasons.append("quantidade compatível")
            if score_tecnico >= 80:
                compatibility_reasons.append("regras técnicas compatíveis")
            if logger.isEnabledFor(logging.DEBUG):
                for motivo in compatibility_reasons:
                    logger.debug("[compatibility_reason] motivo=%s descricao=%r", motivo, descricao)
            logger_extra = {
                "score_textual": analise["score"],
                "score_categoria": categoria["score"],
                "score_quantidade": score_quantidade,
                "score_tecnico": score_tecnico,
                "score_recencia": score_recencia,
                "score_fonte": score_fonte,
            }

            resultados.append({
                "score": score_final,
                "score_textual": analise["score"],
                "score_final_componentes": logger_extra,
                "compatibilidade_categoria": categoria,
                "compatibility_reasons": compatibility_reasons,
                "rejection_reasons": list(categoria.get("rejection_reasons") or []),
                "categoria_detectada": categoria.get("categoria_detectada"),
                "score_quantidade": score_quantidade,
                "fonte_prioridade": score_fonte,
                "especificacao_critica": especificacao,
                "modo_busca": modo,
                "linha_csv": index + 2,
                "descricao": descricao,
                "qtd": qtd_raw,
                "unidade": unidade_resultado,

                "orgao": pegar_coluna(row, ["Órgão", "Orgao", "�rg�o"]),
                "modalidade": pegar_coluna(row, ["Modalidade"]),
                "nr": pegar_coluna(row, ["Nr.", "Nr"]),
                "ano": pegar_coluna(row, ["Ano"]),
                "objeto": pegar_coluna(row, ["Objeto"]),

                "valor_unitario": valor_unitario,
                "valor_total": valor_total,

                "data": pegar_coluna(row, ["Abertura"]),
                "data_homologacao": pegar_coluna(row, ["Data Homologacao"]),
                "vencedor": vencedor,
                "cpf_cnpj": pegar_coluna(row, ["CPF/CNPJ", "CNPJ"]),
                "link_licitacon": pegar_coluna(row, ["Link LicitaCon", "LINK_LICITACON_CIDADAO"]),
                "fonte_base": fonte_base,
                "municipio_fonte": pegar_coluna(row, ["Municipio Fonte"]),
                "grupo_regional": pegar_coluna(row, ["Grupo Regional"]),

                "quantidade_fora": quantidade_fora,
                "avisos_tecnicos": " | ".join(regras["avisos"]),
                "score_details": logger_extra,
                "alertas_preco": alertas_preco,
                "compatibilidade_status": "VALIDO",
            })

    ordenados = sorted(resultados, key=lambda x: x["score"], reverse=True)
    if stats is not None:
        stats["resultados_finais"] = stats.get("resultados_finais", 0) + len(ordenados)
    return ordenados


# ============================================================
# JUNÇÃO / DEDUPLICAÇÃO
# ============================================================

def juntar_resultados(*listas):
    todos = []

    for lista in listas:
        todos.extend(lista)

    vistos = {}

    prioridade_modo = {
        "rigido": 3,
        "relaxado": 2,
        "amplo": 1
    }

    for r in todos:
        chave = (r["linha_csv"], r["orgao"], r["descricao"])

        if chave not in vistos:
            vistos[chave] = r
        else:
            atual = vistos[chave]

            if r["score"] > atual["score"]:
                vistos[chave] = r

            elif r["score"] == atual["score"]:
                prioridade_nova = prioridade_modo.get(r["modo_busca"], 0)
                prioridade_atual = prioridade_modo.get(atual["modo_busca"], 0)

                if prioridade_nova > prioridade_atual:
                    vistos[chave] = r

                elif prioridade_nova == prioridade_atual:
                    if not r.get("quantidade_fora") and atual.get("quantidade_fora"):
                        vistos[chave] = r

    return sorted(
        vistos.values(),
        key=lambda x: (
            x["score"],
            prioridade_modo.get(x["modo_busca"], 0),
            not x.get("quantidade_fora", False)
        ),
        reverse=True
    )
