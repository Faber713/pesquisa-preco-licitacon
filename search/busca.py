from config.app_settings import (
    LIMIAR_RIGIDO,
    LIMIAR_RELAXADO,
    LIMIAR_AMPLO,
    MIN_PCT_OBRIGATORIOS_RIGIDO,
    MIN_PCT_OBRIGATORIOS_RELAXADO,
    MIN_PCT_OBRIGATORIOS_AMPLO,
    LIMIAR_RELAXADO_SEM_QTD,
    LIMIAR_AMPLO_SEM_QTD,
    EXIGIR_VENCEDOR_HOMOLOGADO,
    MAX_RESULTADOS_REAIS,
    PENALIDADE_QUANTIDADE_MAX,
    PENALIDADE_SEM_VENCEDOR,
    SCORE_PIPELINE_EARLY_STOP_MIN_SCORE,
    SCORE_PIPELINE_EARLY_STOP_TOP,
    SCORE_PIPELINE_INTERMEDIARIO_MAX,
    SCORE_PIPELINE_MIN_INTERMEDIARIO,
    SCORE_PIPELINE_MIN_RELEVANTES,
    SCORE_PIPELINE_PESADO_HARD_MAX,
    SCORE_PIPELINE_PESADO_MAX,
    SCORE_PIPELINE_PRE_FILTRO_MAX,
)

from functools import lru_cache
import logging
import re
import time

from ia.regras_tecnicas import validar_regras_tecnicas
from ia.regras_produtos_eletricos import validar_produto_eletrico
from utils.util import pegar_coluna, converter_numero, palavras_fortes, termos_compativeis, normalizar
from search.score import calcular_score
from search.technical import (
    STOPWORDS_TECNICAS,
    calcular_penalidades_tecnicas,
    consulta_generica,
    detectar_categoria_semantica,
    extrair_nucleo_semantico,
    obter_category_profile,
    parse_atributos_tecnicos,
    texto_sem_stopwords_tecnicas,
    validar_compatibilidade_critica,
)
from rapidfuzz import fuzz


logger = logging.getLogger(__name__)
_SCORE_INTERMEDIARIO_CACHE = {}
_SCORE_INTERMEDIARIO_CACHE_MAX = 100000
_RANKING_CORE_CACHE = {}
_RANKING_CORE_CACHE_MAX = 2000
_PIPELINE_CACHE = {}
_PIPELINE_CACHE_MAX = 2000


class SearchResults(list):
    def __init__(self, valores=None, pipeline_stats=None):
        super().__init__(valores or [])
        self.pipeline_stats = pipeline_stats or {}



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


def calcular_penalidade_quantidade(qtd, qtd_min, qtd_max):
    if qtd is None:
        return PENALIDADE_QUANTIDADE_MAX

    if qtd_min <= qtd <= qtd_max:
        return 0

    alvo = (qtd_min + qtd_max) / 2
    if alvo <= 0:
        alvo = qtd_min or qtd_max or 1

    distancia = min(abs(qtd - qtd_min), abs(qtd - qtd_max))
    diferenca_relativa = distancia / max(abs(alvo), 1)

    if diferenca_relativa <= 0.10:
        return 2
    if diferenca_relativa <= 0.50:
        return 8
    if diferenca_relativa <= 0.80:
        return 18
    if diferenca_relativa <= 2:
        return 28
    return PENALIDADE_QUANTIDADE_MAX


@lru_cache(maxsize=50000)
def _semantic_base_cache(descricao):
    texto_norm = normalizar(descricao)
    texto_score = texto_sem_stopwords_tecnicas(descricao)
    tokens = tuple(
        token
        for token in texto_score.split()
        if token and token not in STOPWORDS_TECNICAS
    )
    numeros = tuple(re.findall(r"\b\d+(?:[,.]\d+)?\b", texto_norm))
    medidas = tuple(
        re.findall(r"\b\d+(?:[,.]\d+)?\s*(?:mm|cm|ml|lt|kg|g|amp|a|v|w|pol)\b", texto_norm)
    )
    return {
        "texto_norm": texto_norm,
        "texto_score": texto_score,
        "tokens": tokens,
        "tokens_set": frozenset(tokens),
        "numeros": numeros,
        "medidas": medidas,
    }


def _atributos_leves(descricao):
    semantica = _semantic_base_cache(str(descricao or ""))
    return {
        "numeros": set(semantica["numeros"]),
        "medidas": set(m.replace(" ", "") for m in semantica["medidas"]),
    }


def _score_leve_candidato(ctx_busca, sem_base, qtd, qtd_min, qtd_max, penalidade_quantidade):
    tokens_busca = ctx_busca["tokens_set"]
    tokens_base = sem_base["tokens_set"]
    comuns = tokens_busca.intersection(tokens_base)
    score = len(comuns) * 24

    if ctx_busca["primeiro_token"] and ctx_busca["primeiro_token"] in tokens_base:
        score += 18

    if ctx_busca["atributos_leves"]["medidas"]:
        if ctx_busca["atributos_leves"]["medidas"].intersection(set(m.replace(" ", "") for m in sem_base["medidas"])):
            score += 35
        else:
            score -= 18

    if ctx_busca["atributos_leves"]["numeros"]:
        numeros_base = set(sem_base["numeros"])
        if ctx_busca["atributos_leves"]["numeros"].intersection(numeros_base):
            score += 36 if ctx_busca["consulta_generica"] else 24
        elif numeros_base:
            score -= 20

    if ctx_busca["consulta_generica"] and not ctx_busca["atributos_tecnicos"]["atributos_criticos"]:
        score -= 12

    if qtd_min <= qtd <= qtd_max:
        score += 10
    else:
        score -= min(20, penalidade_quantidade)

    return score


def _penalidade_intermediaria_tecnica(ctx_busca, descricao):
    penalidade = 0
    avisos = []
    base = parse_atributos_tecnicos(str(descricao or ""))

    for chave, esperado in ctx_busca["atributos_tecnicos"]["atributos_criticos"].items():
        encontrado = base["atributos_criticos"].get(chave)
        if not encontrado:
            if chave == "numero":
                penalidade += 14
                avisos.append("numero ausente")
            continue
        if esperado.get("unidade") != encontrado.get("unidade"):
            penalidade += 12
            avisos.append(f"{chave} unidade divergente")
            continue
        if esperado.get("valor") != encontrado.get("valor"):
            penalidade += 30 if chave == "numero" else 22
            avisos.append(f"{chave} divergente")

    material_busca = ctx_busca["atributos_tecnicos"]["atributos_secundarios"].get("material")
    material_base = base["atributos_secundarios"].get("material")
    if material_busca and material_base and material_busca != material_base:
        penalidade += 12
        avisos.append("material divergente")

    return penalidade, avisos


def _score_intermediario_candidato(ctx_busca, candidato):
    descricao = candidato["descricao"]
    sem_base = candidato["semantica"]
    cache_id = candidato.get("cache_id") or descricao
    cache_key = (ctx_busca.get("semantic_core") or ctx_busca["texto_score"], cache_id)
    cached = _SCORE_INTERMEDIARIO_CACHE.get(cache_key)
    if cached is None:
        token_set = fuzz.token_set_ratio(ctx_busca["core_score_text"], sem_base["texto_score"])
        comuns = len(ctx_busca["core_tokens_set"].intersection(sem_base["tokens_set"]))
        cached = {
            "token_set": token_set,
            "comuns": comuns,
        }
        if len(_SCORE_INTERMEDIARIO_CACHE) >= _SCORE_INTERMEDIARIO_CACHE_MAX:
            _SCORE_INTERMEDIARIO_CACHE.clear()
        _SCORE_INTERMEDIARIO_CACHE[cache_key] = cached
    else:
        logger.debug(
            "[cache_core] score_intermediario reutilizado core=%r candidato=%r",
            ctx_busca.get("semantic_core"),
            cache_id,
        )
    penalidade_tecnica, avisos = _penalidade_intermediaria_tecnica(ctx_busca, descricao)
    token_set = cached["token_set"]
    comuns = cached["comuns"]
    score = token_set + min(15, comuns * 3) - penalidade_tecnica - candidato["penalidade_quantidade"] * 0.35
    candidato["score_intermediario"] = score
    candidato["avisos_intermediarios"] = avisos
    return score


def _rerank_variante(ctx_busca, candidato, score):
    atributos = ctx_busca.get("atributos_variantes", {})
    if not atributos:
        return score
    analise_base = parse_atributos_tecnicos(str(candidato.get("descricao") or ""))
    ajuste = 0
    numero = atributos.get("numero")
    if numero:
        numero_base = analise_base.get("atributos_criticos", {}).get("numero")
        if numero_base and numero_base.get("valor") == numero.get("valor"):
            ajuste += 12
        elif numero_base:
            ajuste -= 28
        else:
            ajuste -= 8
    cor = atributos.get("cor")
    if cor:
        cor_base = analise_base.get("atributos_secundarios", {}).get("cor")
        if cor_base and cor_base == cor:
            ajuste += 4
        elif cor_base:
            ajuste -= 4
    ajustado = score + ajuste
    logger.debug(
        "[rerank_variante] core=%r candidato=%r ajuste=%s score=%s score_ajustado=%s",
        ctx_busca.get("semantic_core"),
        candidato.get("cache_id") or candidato.get("descricao"),
        ajuste,
        round(score, 2),
        round(ajustado, 2),
    )
    return ajustado


def _limites_pipeline(ctx_busca, total, modo):
    atributos = ctx_busca["atributos_tecnicos"]["atributos_criticos"]
    fator_tecnico = 1.25 if atributos else 1.0
    fator_modo = 1.25 if modo == "amplo" else 1.1 if modo == "relaxado" else 1.0
    fator_generico = 0.75 if ctx_busca.get("consulta_generica") else 1.0

    pre = int(SCORE_PIPELINE_PRE_FILTRO_MAX * fator_tecnico * fator_modo * fator_generico)
    intermediario = int(SCORE_PIPELINE_INTERMEDIARIO_MAX * fator_tecnico * fator_modo * fator_generico)
    pesado = int(SCORE_PIPELINE_PESADO_MAX * fator_tecnico * fator_modo * fator_generico)

    return {
        "pre": min(total, max(60, pre)),
        "intermediario": min(total, max(25, intermediario)),
        "pesado": min(total, SCORE_PIPELINE_PESADO_HARD_MAX, max(18, pesado)),
    }


def _ranking_core_cache_key(ctx_busca, modo, qtd_min, qtd_max, ignorar_quantidade, exigir_homologacao):
    variantes = ctx_busca.get("atributos_variantes") or {}
    if not ctx_busca.get("semantic_core") or not variantes:
        return None

    # Reuso de ranking final é seguro para variantes fracas, como cor.
    # Número/medida ficam fora porque são atributos críticos do produto.
    if set(variantes) - {"cor"}:
        return None

    return (
        ctx_busca["semantic_core"],
        modo,
        round(float(qtd_min or 0), 4),
        round(float(qtd_max or 0), 4),
        bool(ignorar_quantidade),
        bool(exigir_homologacao),
    )


def _salvar_ranking_core(cache_key, ctx_busca, modo, candidatos):
    if not cache_key or not candidatos:
        return
    if len(_RANKING_CORE_CACHE) >= _RANKING_CORE_CACHE_MAX:
        _RANKING_CORE_CACHE.clear()
    _RANKING_CORE_CACHE[cache_key] = [candidato["cache_id"] for candidato in candidatos]
    logger.info(
        "[cache_core] ranking_salvo core=%r modo=%s candidatos=%s",
        ctx_busca.get("semantic_core"),
        modo,
        len(candidatos),
    )


def _pipeline_cache_key(ctx_busca, modo, qtd_min, qtd_max, ignorar_quantidade, exigir_homologacao):
    core = ctx_busca.get("semantic_core")
    if not core:
        return None
    return (
        core,
        modo,
        round(float(qtd_min or 0), 4),
        round(float(qtd_max or 0), 4),
        bool(ignorar_quantidade),
        bool(exigir_homologacao),
    )


def _salvar_pipeline_cache(cache_key, ctx_busca, modo, candidatos):
    if not cache_key or not candidatos:
        return
    if len(_PIPELINE_CACHE) >= _PIPELINE_CACHE_MAX:
        _PIPELINE_CACHE.clear()
    _PIPELINE_CACHE[cache_key] = [
        {
            chave: valor
            for chave, valor in candidato.items()
            if chave not in {"score_intermediario", "avisos_intermediarios"}
        }
        for candidato in candidatos[:SCORE_PIPELINE_PESADO_HARD_MAX]
    ]
    logger.info(
        "[cache_pipeline_miss] grupo_semantico=%r modo=%s cache_salvo=True candidatos=%s",
        ctx_busca.get("grupo_semantico") or ctx_busca.get("semantic_core"),
        modo,
        min(len(candidatos), SCORE_PIPELINE_PESADO_HARD_MAX),
    )


def _preparar_candidatos_df(df, ctx_busca, qtd_min, qtd_max, ignorar_quantidade, exigir_homologacao):
    candidatos = []

    for index, row in df.iterrows():
        if exigir_homologacao and EXIGIR_VENCEDOR_HOMOLOGADO and not registro_tem_homologacao_valida(row):
            continue

        descricao = pegar_coluna(row, ["Item", "item", "ITEM", "DescriÃ§Ã£o", "Descricao"])
        if not descricao:
            continue

        qtd_raw = pegar_coluna(row, ["Qtd.", "Qtd", "Quantidade", "QUANTIDADE"])
        qtd = converter_numero(qtd_raw)
        if qtd is None:
            continue

        quantidade_fora = not (qtd_min <= qtd <= qtd_max)
        penalidade_quantidade = 0 if ignorar_quantidade else calcular_penalidade_quantidade(qtd, qtd_min, qtd_max)
        semantica = _semantic_base_cache(str(descricao or ""))
        score_leve = _score_leve_candidato(
            ctx_busca,
            semantica,
            qtd,
            qtd_min,
            qtd_max,
            penalidade_quantidade,
        )

        candidatos.append({
            "index": index,
            "row": row,
            "descricao": descricao,
            "qtd_raw": qtd_raw,
            "qtd": qtd,
            "quantidade_fora": quantidade_fora,
            "penalidade_quantidade": penalidade_quantidade,
            "unidade_resultado": pegar_coluna(row, ["Un.", "Un", "Unidade"]),
            "vencedor": obter_vencedor(row),
            "semantica": semantica,
            "score_leve": score_leve,
            "cache_id": pegar_coluna(row, ["_operacional_id", "Linha CSV", "linha_csv"]) or f"{index}:{descricao}",
        })

    return candidatos


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


def calcular_aderencia_textual(descricao_busca, descricao_resultado):
    fortes_busca = palavras_fortes(descricao_busca)
    if not fortes_busca:
        return 1.0, []
    resultado_norm = normalizar(descricao_resultado)
    encontrados = [
        termo for termo in fortes_busca
        if termos_compativeis(termo, resultado_norm)
    ]
    return len(encontrados) / max(len(fortes_busca), 1), encontrados


def aplicar_aderencia_adaptativa(analise, descricao_busca, descricao_resultado, profile):
    aderencia, encontrados = calcular_aderencia_textual(descricao_busca, descricao_resultado)
    minimo = float(profile.get("aderencia_minima", 0.3))
    categoria = profile.get("categoria", "generica")
    logger.info(
        "[aderencia] categoria=%s score=%s aderencia=%s minimo=%s encontrados=%s",
        categoria,
        round(analise.get("score", 0), 2),
        round(aderencia, 3),
        minimo,
        encontrados,
    )
    logger.info(
        "[aderencia_final] categoria=%s score=%s aderencia=%s minimo=%s rigidez=%s",
        categoria,
        round(analise.get("score", 0), 2),
        round(aderencia, 3),
        minimo,
        profile.get("rigidez"),
    )

    if aderencia >= minimo:
        return True, 0, encontrados

    deficit = max(0, minimo - aderencia)
    if profile.get("rigidez") == "alta":
        logger.info(
            "[score_hard_divergence] categoria=%s motivo=aderencia_textual aderencia=%s minimo=%s",
            categoria,
            round(aderencia, 3),
            minimo,
        )
        logger.info(
            "[expansao_hard_abort] categoria=%s motivo=aderencia_textual aderencia=%s minimo=%s",
            categoria,
            round(aderencia, 3),
            minimo,
        )
        return False, 0, encontrados

    penalidade = min(35, max(6, int(deficit * 60)))
    analise["score"] = max(0, analise.get("score", 0) - penalidade)
    logger.info(
        "[score_soft_penalty] categoria=%s motivo=aderencia_textual penalidade=-%s score=%s",
        categoria,
        penalidade,
        round(analise["score"], 2),
    )
    logger.info(
        "[expansao_soft_penalty] categoria=%s motivo=aderencia_textual penalidade=-%s score=%s",
        categoria,
        penalidade,
        round(analise["score"], 2),
    )
    return True, penalidade, encontrados


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
    max_score_pesado=None,
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

    inicio_pipeline = time.perf_counter()
    ctx_busca = _semantic_base_cache(str(descricao_busca or ""))
    ctx_busca = dict(ctx_busca)
    nucleo_semantico = extrair_nucleo_semantico(str(descricao_busca or ""))
    ctx_busca["atributos_leves"] = _atributos_leves(descricao_busca)
    ctx_busca["atributos_tecnicos"] = parse_atributos_tecnicos(str(descricao_busca or ""))
    ctx_busca["categoria"] = detectar_categoria_semantica(str(descricao_busca or ""))
    ctx_busca["category_profile"] = obter_category_profile(ctx_busca["categoria"])
    ctx_busca["primeiro_token"] = ctx_busca["tokens"][0] if ctx_busca["tokens"] else ""
    ctx_busca["consulta_generica"] = consulta_generica(descricao_busca)
    ctx_busca["semantic_core"] = nucleo_semantico.get("semantic_core", "")
    ctx_busca["grupo_semantico"] = nucleo_semantico.get("grupo_semantico", ctx_busca["semantic_core"])
    ctx_busca["atributos_variantes"] = nucleo_semantico.get("atributos_variantes", {})
    ctx_busca["core_score_text"] = texto_sem_stopwords_tecnicas(nucleo_semantico.get("semantic_core") or descricao_busca)
    ctx_busca["core_tokens_set"] = frozenset(ctx_busca["core_score_text"].split())

    candidatos_preparados = []
    tempo_pre_inicio = time.perf_counter()

    for index, row in df.iterrows():

        if exigir_homologacao and EXIGIR_VENCEDOR_HOMOLOGADO and not registro_tem_homologacao_valida(row):
            continue

        descricao = pegar_coluna(row, ["Item", "item", "ITEM", "Descrição", "Descricao"])
        if not descricao:
            continue

        qtd_raw = pegar_coluna(row, ["Qtd.", "Qtd", "Quantidade", "QUANTIDADE"])
        qtd = converter_numero(qtd_raw)

        if qtd is None:
            continue

        quantidade_fora = not (qtd_min <= qtd <= qtd_max)
        penalidade_quantidade = 0 if ignorar_quantidade else calcular_penalidade_quantidade(qtd, qtd_min, qtd_max)
        unidade_resultado = pegar_coluna(row, ["Un.", "Un", "Unidade"])
        vencedor = obter_vencedor(row)
        semantica = _semantic_base_cache(str(descricao or ""))
        score_leve = _score_leve_candidato(
            ctx_busca,
            semantica,
            qtd,
            qtd_min,
            qtd_max,
            penalidade_quantidade,
        )

        candidatos_preparados.append({
            "index": index,
            "row": row,
            "descricao": descricao,
            "qtd_raw": qtd_raw,
            "qtd": qtd,
            "quantidade_fora": quantidade_fora,
            "penalidade_quantidade": penalidade_quantidade,
            "unidade_resultado": unidade_resultado,
            "vencedor": vencedor,
            "semantica": semantica,
            "score_leve": score_leve,
            "cache_id": pegar_coluna(row, ["_operacional_id", "Linha CSV", "linha_csv"]) or f"{index}:{descricao}",
        })

    candidatos_iniciais = len(candidatos_preparados)
    limites = _limites_pipeline(ctx_busca, candidatos_iniciais, modo)
    pipeline_cache_key = _pipeline_cache_key(
        ctx_busca,
        modo,
        qtd_min,
        qtd_max,
        ignorar_quantidade,
        exigir_homologacao,
    )
    pipeline_cache_hit = False
    ranking_cache_key = _ranking_core_cache_key(
        ctx_busca,
        modo,
        qtd_min,
        qtd_max,
        ignorar_quantidade,
        exigir_homologacao,
    )
    ranking_cache_hit = False
    candidatos_pre = []
    cached_pipeline = _PIPELINE_CACHE.get(pipeline_cache_key) if pipeline_cache_key else None
    if cached_pipeline:
        candidatos_por_id = {candidato["cache_id"]: candidato for candidato in candidatos_preparados}
        candidatos_pre = [
            candidatos_por_id[candidato["cache_id"]]
            for candidato in cached_pipeline
            if candidato["cache_id"] in candidatos_por_id
        ][:limites["intermediario"]]
        pipeline_cache_hit = bool(candidatos_pre)
        if pipeline_cache_hit:
            ranking_cache_hit = True
            logger.info(
                "[cache_pipeline_hit] grupo_semantico=%r modo=%s candidatos=%s",
                ctx_busca.get("grupo_semantico") or ctx_busca.get("semantic_core"),
                modo,
                len(candidatos_pre),
            )
    else:
        logger.info(
            "[cache_pipeline_miss] grupo_semantico=%r modo=%s",
            ctx_busca.get("grupo_semantico") or ctx_busca.get("semantic_core"),
            modo,
        )
    ids_ranking_cache = _RANKING_CORE_CACHE.get(ranking_cache_key) if ranking_cache_key else None
    if not pipeline_cache_hit and ids_ranking_cache:
        candidatos_por_id = {candidato["cache_id"]: candidato for candidato in candidatos_preparados}
        candidatos_pre = [
            candidatos_por_id[cache_id]
            for cache_id in ids_ranking_cache
            if cache_id in candidatos_por_id
        ][:limites["intermediario"]]
        ranking_cache_hit = bool(candidatos_pre)
        if ranking_cache_hit:
            logger.info(
                "[cache_core] ranking_reutilizado core=%r modo=%s candidatos=%s",
                ctx_busca.get("semantic_core"),
                modo,
                len(candidatos_pre),
            )

    if not ranking_cache_hit:
        preservados_fts = candidatos_preparados[:min(candidatos_iniciais, 40)]
        candidatos_preparados.sort(key=lambda item: item["score_leve"], reverse=True)
        candidatos_pre = candidatos_preparados[:limites["pre"]]
        vistos_pre = {id(candidato["row"]) for candidato in candidatos_pre}
        for candidato in preservados_fts:
            chave = id(candidato["row"])
            if chave not in vistos_pre and len(candidatos_pre) < limites["pre"]:
                candidatos_pre.append(candidato)
                vistos_pre.add(chave)
    tempo_pre_ms = round((time.perf_counter() - tempo_pre_inicio) * 1000, 2)

    tempo_inter_inicio = time.perf_counter()
    for candidato in candidatos_pre:
        score_intermediario = _score_intermediario_candidato(ctx_busca, candidato)
        candidato["score_intermediario"] = _rerank_variante(ctx_busca, candidato, score_intermediario)

    candidatos_pre.sort(key=lambda item: item.get("score_intermediario", 0), reverse=True)
    rigidez_categoria = ctx_busca["category_profile"].get("rigidez", "media")
    score_minimo_categoria = int(ctx_busca["category_profile"].get("score_minimo", 35))
    minimo_intermediario = SCORE_PIPELINE_MIN_INTERMEDIARIO
    if rigidez_categoria != "alta":
        minimo_intermediario = min(SCORE_PIPELINE_MIN_INTERMEDIARIO, score_minimo_categoria)
    candidatos_intermediarios = [
        candidato
        for candidato in candidatos_pre
        if candidato.get("score_intermediario", 0) >= minimo_intermediario
    ][:limites["intermediario"]]
    if not candidatos_intermediarios and rigidez_categoria != "alta" and candidatos_pre:
        candidatos_intermediarios = [
            candidato
            for candidato in candidatos_pre
            if candidato.get("score_intermediario", 0) > 0
        ][:min(limites["pesado"], limites["intermediario"])]
        if not candidatos_intermediarios:
            candidatos_intermediarios = candidatos_pre[:min(limites["pesado"], limites["intermediario"])]
        logger.info(
            "[expansao_soft_penalty] categoria=%s motivo=intermediario_baixo minimo=%s candidatos_preservados=%s",
            ctx_busca["categoria"],
            minimo_intermediario,
            len(candidatos_intermediarios),
        )
    if not ranking_cache_hit:
        _salvar_ranking_core(ranking_cache_key, ctx_busca, modo, candidatos_intermediarios)
        _salvar_pipeline_cache(pipeline_cache_key, ctx_busca, modo, candidatos_intermediarios)

    motivo_aborto = ""
    top_intermediario = candidatos_intermediarios[0].get("score_intermediario", 0) if candidatos_intermediarios else 0
    relevantes_intermediarios = sum(
        1
        for candidato in candidatos_intermediarios
        if candidato.get("score_intermediario", 0) >= max(SCORE_PIPELINE_MIN_INTERMEDIARIO, 45)
    )

    if not candidatos_preparados:
        motivo_aborto = "sem_candidatos"
    elif not candidatos_intermediarios and rigidez_categoria == "alta":
        motivo_aborto = "score_baixo"
    elif (
        rigidez_categoria == "alta"
        and (top_intermediario < SCORE_PIPELINE_MIN_INTERMEDIARIO or relevantes_intermediarios < SCORE_PIPELINE_MIN_RELEVANTES)
    ):
        motivo_aborto = "baixa_aderencia"
    elif (
        rigidez_categoria == "alta"
        and ctx_busca["consulta_generica"]
        and not ctx_busca["atributos_tecnicos"]["atributos_criticos"]
        and top_intermediario < 60
    ):
        motivo_aborto = "consulta_generica"

    early_stop = False
    if motivo_aborto:
        candidatos_pesados = []
        early_stop = True
    elif len(candidatos_intermediarios) >= SCORE_PIPELINE_EARLY_STOP_TOP:
        melhores = candidatos_intermediarios[:SCORE_PIPELINE_EARLY_STOP_TOP]
        diversidade = len({(c["descricao"], c["vencedor"]) for c in melhores})
        if (
            min(c.get("score_intermediario", 0) for c in melhores) >= SCORE_PIPELINE_EARLY_STOP_MIN_SCORE
            and diversidade >= min(12, SCORE_PIPELINE_EARLY_STOP_TOP)
        ):
            candidatos_pesados = melhores
            early_stop = True
        else:
            candidatos_pesados = candidatos_intermediarios[:limites["pesado"]]
    else:
        candidatos_pesados = candidatos_intermediarios[:limites["pesado"]]

    limite_pesado_chamada = SCORE_PIPELINE_PESADO_HARD_MAX
    if max_score_pesado is not None:
        limite_pesado_chamada = max(0, min(SCORE_PIPELINE_PESADO_HARD_MAX, int(max_score_pesado)))

    if len(candidatos_pesados) > limite_pesado_chamada:
        logger.info(
            "[early_stop] motivo=limite_pipeline modo=%s score_pesado_planejado=%s hard_limit=%s",
            modo,
            len(candidatos_pesados),
            limite_pesado_chamada,
        )
        candidatos_pesados = candidatos_pesados[:limite_pesado_chamada]
        early_stop = True
        motivo_aborto = motivo_aborto or "limite_pipeline"

    tempo_intermediario_ms = round((time.perf_counter() - tempo_inter_inicio) * 1000, 2)
    tempo_pesado_inicio = time.perf_counter()
    score_pesado_executado = 0
    funil_final = {
        "apos_score": 0,
        "apos_hard_divergence": 0,
        "apos_aderencia": 0,
        "descartes": {},
    }

    def _registrar_descarte(motivo, categoria, score=None, descricao_resultado="", extra=None):
        funil_final["descartes"][motivo] = funil_final["descartes"].get(motivo, 0) + 1
        logger.info(
            "[candidato_descartado] motivo=%s categoria=%s score=%s descricao=%r extra=%s",
            motivo,
            categoria,
            round(score, 2) if isinstance(score, (int, float)) else score,
            descricao_resultado,
            extra or {},
        )

    for candidato in candidatos_pesados:
        index = candidato["index"]
        row = candidato["row"]
        descricao = candidato["descricao"]
        qtd = candidato["qtd"]
        qtd_raw = candidato["qtd_raw"]
        quantidade_fora = candidato["quantidade_fora"]
        penalidade_quantidade = candidato["penalidade_quantidade"]
        unidade_resultado = candidato["unidade_resultado"]
        vencedor = candidato["vencedor"]

        compatibilidade_critica = validar_compatibilidade_critica(descricao_busca, descricao)
        critico_ausente_soft = bool(compatibilidade_critica.get("critical_missing"))
        if not compatibilidade_critica["ok"]:
            if compatibilidade_critica.get("atributo") == "numero":
                logger.info(
                    "[numero_divergente_hard] categoria=%s motivo=%s descricao=%r",
                    compatibilidade_critica["categoria"],
                    compatibilidade_critica["motivo"],
                    descricao,
                )
            logger.info(
                "[score_hard_divergence] categoria=%s motivo=%s atributo=%s",
                compatibilidade_critica["categoria"],
                compatibilidade_critica["motivo"],
                compatibilidade_critica["atributo"],
            )
            _registrar_descarte(
                compatibilidade_critica["motivo"],
                compatibilidade_critica["categoria"],
                score=None,
                descricao_resultado=descricao,
                extra={
                    "etapa": "hard_divergence",
                    "canonical_mismatch": True,
                    "atributo": compatibilidade_critica["atributo"],
                    "descricao_busca": descricao_busca,
                    "atributos_busca": compatibilidade_critica.get("busca", {}).get("atributos_criticos", {}),
                    "atributos_resultado": compatibilidade_critica.get("resultado", {}).get("atributos_criticos", {}),
                },
            )
            continue

        funil_final["apos_hard_divergence"] += 1
        score_pesado_executado += 1
        analise = calcular_score(descricao_usada, descricao, criterios, modo=modo)
        funil_final["apos_score"] += 1
        if compatibilidade_critica.get("soft_divergence"):
            penalidade_soft_critica = 12 if compatibilidade_critica.get("critical_missing") else 15
            analise["score"] = max(0, analise.get("score", 0) - penalidade_soft_critica)
            analise.setdefault("avisos_tecnicos_score", []).append(
                f"{compatibilidade_critica['motivo']} penalidade=-{penalidade_soft_critica}"
            )
            if compatibilidade_critica.get("critical_missing") and compatibilidade_critica.get("atributo") == "numero":
                logger.info(
                    "[numero_ausente_soft] categoria=%s penalidade=-%s score=%s descricao=%r",
                    compatibilidade_critica["categoria"],
                    penalidade_soft_critica,
                    round(analise["score"], 2),
                    descricao,
                )
            logger.info(
                "[score_soft_penalty] categoria=%s motivo=%s penalidade=-%s score=%s",
                compatibilidade_critica["categoria"],
                compatibilidade_critica["motivo"],
                penalidade_soft_critica,
                round(analise["score"], 2),
            )
        if descricao_usada != descricao_busca:
            penalidade_original = calcular_penalidades_tecnicas(descricao_busca, descricao)
            penalidade_extra = max(
                0,
                penalidade_original["penalidade"] - analise.get("penalidade_tecnica", 0),
            )
            if penalidade_extra:
                analise["score"] = max(0, analise["score"] - penalidade_extra)
                analise["penalidade_tecnica"] = analise.get("penalidade_tecnica", 0) + penalidade_extra
                analise.setdefault("avisos_tecnicos_score", []).extend(penalidade_original["avisos"])

        regras = validar_regras_tecnicas(
            descricao_busca=descricao_busca,
            descricao_resultado=descricao,
            unidade_busca=None,
            unidade_resultado=unidade_resultado
        )

        if not regras["ok"]:
            if ctx_busca["category_profile"].get("hard_divergence", False):
                logger.info(
                    "[expansao_hard_abort] categoria=%s motivo=regras_tecnicas avisos=%s",
                    ctx_busca["categoria"],
                    regras.get("avisos", []),
                )
                _registrar_descarte(
                    "regras_tecnicas_hard",
                    ctx_busca["categoria"],
                    analise.get("score"),
                    descricao,
                    extra={
                        "etapa": "regras_tecnicas",
                        "avisos": regras.get("avisos", []),
                        "penalidade": regras.get("penalidade", 0),
                    },
                )
                continue
            penalidade_soft_regras = min(35, max(12, int(regras.get("penalidade", 0) * 0.5) or 12))
            analise["score"] = max(0, analise.get("score", 0) - penalidade_soft_regras)
            logger.info(
                "[expansao_soft_penalty] categoria=%s motivo=regras_tecnicas penalidade=-%s score=%s avisos=%s",
                ctx_busca["categoria"],
                penalidade_soft_regras,
                round(analise["score"], 2),
                regras.get("avisos", []),
            )

        ok_aderencia, penalidade_aderencia, termos_fortes_encontrados = aplicar_aderencia_adaptativa(
            analise,
            descricao_busca,
            descricao,
            ctx_busca["category_profile"],
        )

        if not ok_aderencia:
            if critico_ausente_soft:
                penalidade_aderencia = 10
                analise["score"] = max(0, analise.get("score", 0) - penalidade_aderencia)
                analise.setdefault("avisos_tecnicos_score", []).append(
                    f"aderencia baixa com atributo critico ausente penalidade=-{penalidade_aderencia}"
                )
                logger.info(
                    "[numero_ausente_soft] categoria=%s motivo=aderencia_final_soft penalidade=-%s score=%s descricao=%r",
                    ctx_busca["categoria"],
                    penalidade_aderencia,
                    round(analise["score"], 2),
                    descricao,
                )
            else:
                _registrar_descarte(
                    "aderencia_final",
                    ctx_busca["categoria"],
                    analise.get("score"),
                    descricao,
                    extra={
                        "etapa": "aderencia",
                        "termos_fortes_encontrados": termos_fortes_encontrados,
                        "penalidade_aderencia": penalidade_aderencia,
                    },
                )
                continue

        if ok_aderencia or critico_ausente_soft:
            funil_final["apos_aderencia"] += 1
        else:
            _registrar_descarte(
                "aderencia_final",
                ctx_busca["categoria"],
                analise.get("score"),
                descricao,
                extra={
                    "etapa": "aderencia",
                    "termos_fortes_encontrados": termos_fortes_encontrados,
                    "penalidade_aderencia": penalidade_aderencia,
                },
            )
            continue

        analise["score"] = max(0, analise["score"] - regras["penalidade"])
        if penalidade_quantidade:
            analise["score"] = max(0, analise["score"] - penalidade_quantidade)
            logger.debug(
                "[score] quantidade penalizada descricao_busca=%r descricao_resultado=%r qtd=%s faixa=%s-%s penalidade=-%s",
                descricao_busca,
                descricao,
                qtd,
                qtd_min,
                qtd_max,
                penalidade_quantidade,
            )

        vencedor = obter_vencedor(row)
        if not tem_vencedor_homologado(vencedor):
            analise["score"] = max(0, analise["score"] - PENALIDADE_SEM_VENCEDOR)
            logger.debug(
                "[score] vencedor ausente descricao_resultado=%r penalidade=-%s",
                descricao,
                PENALIDADE_SEM_VENCEDOR,
            )

        if ignorar_quantidade and quantidade_fora:
            if modo == "relaxado" and analise["score"] < LIMIAR_RELAXADO_SEM_QTD:
                _registrar_descarte(
                    "quantidade_score_baixo_relaxado",
                    ctx_busca["categoria"],
                    analise.get("score"),
                    descricao,
                    extra={"etapa": "quantidade", "limiar": LIMIAR_RELAXADO_SEM_QTD},
                )
                continue
            if modo == "amplo" and analise["score"] < LIMIAR_AMPLO_SEM_QTD:
                _registrar_descarte(
                    "quantidade_score_baixo_amplo",
                    ctx_busca["categoria"],
                    analise.get("score"),
                    descricao,
                    extra={"etapa": "quantidade", "limiar": LIMIAR_AMPLO_SEM_QTD},
                )
                continue

        if modo == "rigido" and ctx_busca["category_profile"].get("rigidez") == "alta":
            if analise["pct_obrigatorios"] < (min_pct_obrigatorios * 100):
                _registrar_descarte(
                    "obrigatorios_insuficientes",
                    ctx_busca["categoria"],
                    analise.get("score"),
                    descricao,
                    extra={
                        "etapa": "pct_obrigatorios",
                        "pct_obrigatorios": analise.get("pct_obrigatorios"),
                        "minimo": min_pct_obrigatorios * 100,
                    },
                )
                continue

        if rigidez_categoria == "alta":
            score_util_minimo = max(limiar, score_minimo_categoria)
        else:
            score_util_minimo = score_minimo_categoria
        if critico_ausente_soft:
            score_util_minimo = max(limiar, score_util_minimo - 25)
        logger.info(
            "[filtro_final_categoria] categoria=%s modo=%s rigidez=%s score=%s score_minimo=%s",
            ctx_busca["categoria"],
            modo,
            rigidez_categoria,
            round(analise["score"], 2),
            score_util_minimo,
        )
        if analise["score"] >= score_util_minimo:
            valor_unitario = obter_valor_unitario(row)
            valor_total = obter_valor_total(row)
            avisos_score = []
            avisos_score.extend(analise.get("avisos_tecnicos_score", []))
            if regras["avisos"]:
                avisos_score.extend(regras["avisos"])
            if penalidade_quantidade:
                avisos_score.append(
                    f"quantidade divergente: pesquisa={qtd_min:g}-{qtd_max:g} resultado={qtd:g} penalidade=-{penalidade_quantidade}"
                )
            if penalidade_aderencia:
                avisos_score.append(f"aderencia textual baixa penalidade=-{penalidade_aderencia}")
            if not tem_vencedor_homologado(vencedor):
                avisos_score.append(f"vencedor ausente penalidade=-{PENALIDADE_SEM_VENCEDOR}")

            resultados.append({
                "score": analise["score"],
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
                "fonte_base": pegar_coluna(row, ["Fonte Base"]),
                "municipio_fonte": pegar_coluna(row, ["Municipio Fonte"]),
                "grupo_regional": pegar_coluna(row, ["Grupo Regional"]),

                "quantidade_fora": quantidade_fora,
                "avisos_tecnicos": " | ".join(avisos_score),
                "penalidade_quantidade": penalidade_quantidade,
                "penalidade_tecnica": analise.get("penalidade_tecnica", 0),
                "critico_ausente_soft": critico_ausente_soft,
                "atributo_critico_ausente": (
                    compatibilidade_critica.get("atributo") if critico_ausente_soft else ""
                ),
            })
            if len(resultados) >= MAX_RESULTADOS_REAIS:
                early_stop = True
                motivo_aborto = motivo_aborto or "limite_resultados"
                logger.info(
                    "[early_stop] motivo=limite_resultados max_resultados=%s modo=%s",
                    MAX_RESULTADOS_REAIS,
                    modo,
                )
                break
        else:
            _registrar_descarte(
                "score_minimo",
                ctx_busca["categoria"],
                analise.get("score"),
                descricao,
                extra={
                    "etapa": "filtro_final",
                    "score_minimo": score_util_minimo,
                    "modo": modo,
                    "rigidez": rigidez_categoria,
                    "score_intermediario": candidato.get("score_intermediario"),
                },
            )

        if (
            not early_stop
            and len(resultados) >= SCORE_PIPELINE_EARLY_STOP_TOP
            and min(r["score"] for r in resultados[:SCORE_PIPELINE_EARLY_STOP_TOP]) >= SCORE_PIPELINE_EARLY_STOP_MIN_SCORE
            and len({(r["descricao"], r["vencedor"]) for r in resultados[:SCORE_PIPELINE_EARLY_STOP_TOP]}) >= 12
        ):
            early_stop = True
            motivo_aborto = motivo_aborto or "queda_relevancia"
            logger.info(
                "[early_stop] motivo=queda_relevancia modo=%s resultados=%s",
                modo,
                len(resultados),
            )
            break

    tempo_pesado_ms = round((time.perf_counter() - tempo_pesado_inicio) * 1000, 2)
    tempo_total_ms = round((time.perf_counter() - inicio_pipeline) * 1000, 2)
    logger.info(
        "[funil_pipeline] modo=%s categoria=%s rigidez=%s fts=%s apos_pre=%s apos_intermediario=%s score_pesado_planejado=%s apos_hard_divergence=%s apos_score=%s apos_aderencia=%s resultado_final=%s motivo_aborto=%s descartes=%s",
        modo,
        ctx_busca["categoria"],
        rigidez_categoria,
        candidatos_iniciais,
        len(candidatos_pre),
        len(candidatos_intermediarios),
        len(candidatos_pesados),
        funil_final["apos_hard_divergence"],
        funil_final["apos_score"],
        funil_final["apos_aderencia"],
        len(resultados),
        motivo_aborto or "nenhum",
        funil_final["descartes"],
    )
    logger.info(
        "[score_pipeline] modo=%s candidatos_iniciais=%s apos_pre_filtro=%s apos_intermediario=%s score_pesado_real=%s score_pesado=%s resultados=%s early_stop=%s motivo_aborto=%s pipeline_resumo=%s->%s->%s->%s top_intermediario=%s relevantes_intermediarios=%s consulta_generica=%s pipeline_cache_hit=%s ranking_cache_hit=%s tempo_pre_ms=%s tempo_intermediario_ms=%s tempo_pesado_ms=%s tempo_total_ms=%s",
        modo,
        candidatos_iniciais,
        len(candidatos_pre),
        len(candidatos_intermediarios),
        score_pesado_executado,
        len(candidatos_pesados),
        len(resultados),
        early_stop,
        motivo_aborto or "nenhum",
        candidatos_iniciais,
        len(candidatos_pre),
        len(candidatos_intermediarios),
        score_pesado_executado,
        round(top_intermediario, 2),
        relevantes_intermediarios,
        ctx_busca["consulta_generica"],
        pipeline_cache_hit,
        ranking_cache_hit,
        tempo_pre_ms,
        tempo_intermediario_ms,
        tempo_pesado_ms,
        tempo_total_ms,
    )

    pipeline_stats = {
        "modo": modo,
        "candidatos_iniciais": candidatos_iniciais,
        "apos_pre_filtro": len(candidatos_pre),
        "apos_intermediario": len(candidatos_intermediarios),
        "score_pesado": len(candidatos_pesados),
        "score_pesado_real": score_pesado_executado,
        "score_pesado_planejado": len(candidatos_pesados),
        "funil_pipeline": {
            "fts": candidatos_iniciais,
            "apos_pre": len(candidatos_pre),
            "apos_intermediario": len(candidatos_intermediarios),
            "score_pesado_planejado": len(candidatos_pesados),
            "apos_hard_divergence": funil_final["apos_hard_divergence"],
            "apos_score": funil_final["apos_score"],
            "apos_aderencia": funil_final["apos_aderencia"],
            "resultado_final": len(resultados),
            "descartes": dict(funil_final["descartes"]),
        },
        "resultados": len(resultados),
        "early_stop": early_stop,
        "motivo_aborto": motivo_aborto or "",
        "top_intermediario": round(top_intermediario, 2),
        "relevantes_intermediarios": relevantes_intermediarios,
        "consulta_generica": ctx_busca["consulta_generica"],
        "pipeline_cache_hit": pipeline_cache_hit,
        "ranking_cache_hit": ranking_cache_hit,
        "tempo_pre_ms": tempo_pre_ms,
        "tempo_intermediario_ms": tempo_intermediario_ms,
        "tempo_pesado_ms": tempo_pesado_ms,
        "tempo_total_ms": tempo_total_ms,
    }

    return SearchResults(
        sorted(resultados, key=lambda x: x["score"], reverse=True),
        pipeline_stats=pipeline_stats,
    )


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

    ordenados = sorted(
        vistos.values(),
        key=lambda x: (
            x["score"],
            prioridade_modo.get(x["modo_busca"], 0),
            not x.get("quantidade_fora", False)
        ),
        reverse=True
    )
    return ordenados[:MAX_RESULTADOS_REAIS]
