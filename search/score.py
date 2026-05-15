from rapidfuzz import fuzz
import logging

from config.app_settings import (
    PESO_TEXTO,
    PESO_OBRIGATORIOS,
    PESO_IMPORTANTES,
    PESO_FRASES,
    TERMOS_GENERICOS
)

from utils.util import (
    normalizar,
    lista_normalizada,
    contem_termo,
    termos_compativeis,
    palavras_fortes
)
from search.technical import calcular_penalidades_tecnicas, texto_sem_stopwords_tecnicas


logger = logging.getLogger(__name__)


def calcular_score(descricao_busca, descricao_base, criterios, modo="rigido"):
    busca_norm = normalizar(descricao_busca)
    base_norm = normalizar(descricao_base)
    busca_score_norm = texto_sem_stopwords_tecnicas(descricao_busca)
    base_score_norm = texto_sem_stopwords_tecnicas(descricao_base)

    obrigatorios = lista_normalizada(criterios.get("termos_obrigatorios", []))
    importantes = lista_normalizada(criterios.get("termos_importantes", []))
    excluir = lista_normalizada(criterios.get("termos_excluir", []))
    frases_chave = lista_normalizada(criterios.get("frases_chave", []))

    encontrados_obrigatorios = []
    faltantes_obrigatorios = []
    encontrados_importantes = []
    encontrados_excluir = []
    encontradas_frases = []

    for termo in obrigatorios:
        if termos_compativeis(termo, base_norm):
            encontrados_obrigatorios.append(termo)
        else:
            faltantes_obrigatorios.append(termo)

    for termo in importantes:
        if termos_compativeis(termo, base_norm):
            encontrados_importantes.append(termo)

    for termo in excluir:
        if termos_compativeis(termo, base_norm):
            encontrados_excluir.append(termo)

    for frase in frases_chave:
        if contem_termo(base_norm, frase):
            encontradas_frases.append(frase)

    pct_obrigatorios = len(encontrados_obrigatorios) / len(obrigatorios) if obrigatorios else 1
    pct_importantes = len(encontrados_importantes) / len(importantes) if importantes else 0
    pct_frases = len(encontradas_frases) / len(frases_chave) if frases_chave else 0

    score_token_set = fuzz.token_set_ratio(busca_score_norm, base_score_norm)
    score_token_sort = fuzz.token_sort_ratio(busca_score_norm, base_score_norm)
    score_partial = fuzz.partial_ratio(busca_score_norm, base_score_norm)

    score_texto = (
        score_token_set * 0.50 +
        score_token_sort * 0.30 +
        score_partial * 0.20
    )

    if modo == "amplo":
        fortes_busca = palavras_fortes(descricao_busca)
        fortes_encontradas = [
            p for p in fortes_busca
            if termos_compativeis(p, base_norm)
        ]

        if not fortes_busca:
            score = 0
        elif len(fortes_encontradas) == 0:
            score = 0
        else:
            proporcao_fortes = len(fortes_encontradas) / len(fortes_busca)

            score = (
                score_token_set * 0.30 +
                score_token_sort * 0.15 +
                score_partial * 0.15 +
                proporcao_fortes * 100 * 0.35 +
                pct_importantes * 100 * 0.05
            )

            score += min(15, len(fortes_encontradas) * 6)

        score -= len(encontrados_excluir) * 15

        palavras_base = set(base_norm.split())
        palavras_busca = set(busca_norm.split())
        intersecao = palavras_base.intersection(palavras_busca)

        if intersecao and intersecao.issubset(TERMOS_GENERICOS):
            score = 0

    else:
        score = (
            score_texto * PESO_TEXTO +
            pct_obrigatorios * 100 * PESO_OBRIGATORIOS +
            pct_importantes * 100 * PESO_IMPORTANTES +
            pct_frases * 100 * PESO_FRASES
        )

        score -= len(faltantes_obrigatorios) * 8
        score -= len(encontrados_excluir) * 20

        palavras_base = set(base_norm.split())
        palavras_busca = set(busca_norm.split())
        intersecao = palavras_base.intersection(palavras_busca)

        if intersecao and intersecao.issubset(TERMOS_GENERICOS):
            score -= 20

        if encontradas_frases:
            score += min(15, len(encontradas_frases) * 5)

    penalidade_tecnica = calcular_penalidades_tecnicas(descricao_busca, descricao_base)
    if penalidade_tecnica["penalidade"]:
        score -= penalidade_tecnica["penalidade"]
        logger.debug(
            "[score] descricao_busca=%r descricao_resultado=%r penalidade_tecnica=%s avisos=%s",
            descricao_busca,
            descricao_base,
            penalidade_tecnica["penalidade"],
            penalidade_tecnica["avisos"],
        )

    score = max(0, min(100, score))

    return {
        "score": round(score, 2),
        "pct_obrigatorios": round(pct_obrigatorios * 100, 2),
        "obrigatorios_encontrados": encontrados_obrigatorios,
        "importantes_encontrados": encontrados_importantes,
        "obrigatorios_faltantes": faltantes_obrigatorios,
        "termos_exclusao": encontrados_excluir,
        "frases_chave_encontradas": encontradas_frases,
        "score_texto": round(score_texto, 2),
        "penalidade_tecnica": penalidade_tecnica["penalidade"],
        "avisos_tecnicos_score": penalidade_tecnica["avisos"],
        "atributos_busca": penalidade_tecnica["busca"],
        "atributos_resultado": penalidade_tecnica["resultado"],
    }
