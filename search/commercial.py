import logging
import re
from functools import lru_cache

from search.units import normalizar_unidade
from utils.util import converter_numero, normalizar


logger = logging.getLogger("pesquisa.commercial")


PADRAO_RETORNO = {
    "tipo_embalagem": None,
    "quantidade_equivalente": 1,
    "unidade_base_normalizada": None,
    "fator_equivalencia": 1,
    "texto_detectado": [],
}

_NUMERO = r"(?P<quantidade>\d+(?:[,.]\d+)?)"
_SEP = r"[\s,;:\-]*"

_PADROES_EMBALAGEM = [
    {
        "tipo": "PCT",
        "unidade_base": "UN",
        "regex": re.compile(
            rf"\b(?:pacote|pacotes|pct|pcte){_SEP}(?:c\/|com|contendo|de)?{_SEP}{_NUMERO}{_SEP}(?:un|und|unid|unidade|unidades)?\b",
            re.IGNORECASE,
        ),
    },
    {
        "tipo": "CX",
        "unidade_base": "UN",
        "regex": re.compile(
            rf"\b(?:caixa|caixas|cx){_SEP}(?:c\/|com|contendo|de)?{_SEP}{_NUMERO}{_SEP}(?:un|und|unid|unidade|unidades)?\b",
            re.IGNORECASE,
        ),
    },
    {
        "tipo": "KIT",
        "unidade_base": "UN",
        "regex": re.compile(
            rf"\b(?:kit|kits){_SEP}(?:c\/|com|contendo|de)?{_SEP}{_NUMERO}{_SEP}(?:un|und|unid|unidade|unidades|pecas|peças)?\b",
            re.IGNORECASE,
        ),
    },
    {
        "tipo": None,
        "unidade_base": "UN",
        "regex": re.compile(
            rf"\bc\s*/\s*{_NUMERO}\s*(?:un|und|unid|unidade|unidades)?\b",
            re.IGNORECASE,
        ),
    },
]

_PADROES_UNIDADE_MEDIDA = [
    ("ML", re.compile(r"\b\d+(?:[,.]\d+)?\s*ml\b|\bmililitros?\b", re.IGNORECASE)),
    ("KG", re.compile(r"\b\d+(?:[,.]\d+)?\s*kg\b|\bquilogramas?\b", re.IGNORECASE)),
    ("G", re.compile(r"\b\d+(?:[,.]\d+)?\s*g\b|\bgramas?\b", re.IGNORECASE)),
    ("L", re.compile(r"\b\d+(?:[,.]\d+)?\s*l\b|\blitros?\b", re.IGNORECASE)),
]


def _resultado_base():
    return {
        "tipo_embalagem": None,
        "quantidade_equivalente": 1,
        "unidade_base_normalizada": None,
        "fator_equivalencia": 1,
        "texto_detectado": [],
    }


def _numero(valor):
    numero = converter_numero(valor)
    if numero is None:
        return 1
    return int(numero) if float(numero).is_integer() else numero


def _finalizar(resultado):
    quantidade = resultado.get("quantidade_equivalente") or 1
    resultado["quantidade_equivalente"] = quantidade
    resultado["fator_equivalencia"] = quantidade
    resultado["texto_detectado"] = list(dict.fromkeys(resultado.get("texto_detectado") or []))
    return resultado


def _detectar_embalagem_quantificada(descricao):
    for regra in _PADROES_EMBALAGEM:
        match = regra["regex"].search(descricao)
        if not match:
            continue
        quantidade = _numero(match.group("quantidade"))
        tipo = regra["tipo"]
        texto_norm = normalizar(descricao)
        if tipo is None:
            if "kit" in texto_norm:
                tipo = "KIT"
            elif "caixa" in texto_norm or " cx " in f" {texto_norm} ":
                tipo = "CX"
            elif "pacote" in texto_norm or " pct " in f" {texto_norm} ":
                tipo = "PCT"
        resultado = {
            "tipo_embalagem": tipo,
            "quantidade_equivalente": quantidade,
            "unidade_base_normalizada": normalizar_unidade(regra["unidade_base"]),
            "fator_equivalencia": quantidade,
            "texto_detectado": [match.group(0).strip()],
        }
        logger.debug(
            "[composicao_detectada] tipo=%s quantidade=%s texto=%r",
            resultado["tipo_embalagem"],
            quantidade,
            match.group(0).strip(),
        )
        logger.debug(
            "[equivalencia_detectada] fator=%s unidade_base=%s",
            resultado["fator_equivalencia"],
            resultado["unidade_base_normalizada"],
        )
        return resultado
    return None


def _detectar_par(descricao):
    match = re.search(r"\b(?:par|pares)\b", descricao, re.IGNORECASE)
    if not match:
        return None
    resultado = {
        "tipo_embalagem": "PAR",
        "quantidade_equivalente": 2,
        "unidade_base_normalizada": "UN",
        "fator_equivalencia": 2,
        "texto_detectado": [match.group(0).strip()],
    }
    logger.debug("[composicao_detectada] tipo=PAR quantidade=2 texto=%r", match.group(0).strip())
    logger.debug("[equivalencia_detectada] fator=2 unidade_base=UN")
    return resultado


def _detectar_unidade_medida(descricao):
    detectados = []
    unidade = None
    for unidade_detectada, regex in _PADROES_UNIDADE_MEDIDA:
        match = regex.search(descricao)
        if match:
            unidade = unidade_detectada
            detectados.append(match.group(0).strip())
            break
    if not unidade:
        return None
    resultado = _resultado_base()
    resultado["unidade_base_normalizada"] = unidade
    resultado["texto_detectado"] = detectados
    logger.debug("[composicao_detectada] unidade_base=%s texto=%r", unidade, detectados[0])
    return resultado


@lru_cache(maxsize=10000)
def extrair_composicao_comercial(descricao):
    texto = str(descricao or "")
    if not texto.strip():
        return _resultado_base()

    resultado = (
        _detectar_embalagem_quantificada(texto)
        or _detectar_par(texto)
        or _detectar_unidade_medida(texto)
        or _resultado_base()
    )
    return _finalizar(resultado)
