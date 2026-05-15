import logging
import re
from functools import lru_cache

from utils.normalization import remover_acentos


logger = logging.getLogger(__name__)


UNIT_ALIASES = {
    "a": ("amperagem", "a", 1),
    "amp": ("amperagem", "a", 1),
    "ampere": ("amperagem", "a", 1),
    "amperes": ("amperagem", "a", 1),
    "cm": ("medida", "mm", 10),
    "g": ("massa", "g", 1),
    "kg": ("massa", "g", 1000),
    "l": ("volume", "ml", 1000),
    "litro": ("volume", "ml", 1000),
    "litros": ("volume", "ml", 1000),
    "lt": ("volume", "ml", 1000),
    "m": ("medida", "mm", 1000),
    "ml": ("volume", "ml", 1),
    "mm": ("medida", "mm", 1),
    "pol": ("polegadas", "pol", 1),
    "polegada": ("polegadas", "pol", 1),
    "polegadas": ("polegadas", "pol", 1),
    "v": ("tensao", "v", 1),
    "volt": ("tensao", "v", 1),
    "volts": ("tensao", "v", 1),
}

UNIT_PATTERN = re.compile(
    r"(?<![\d,.])(\d+(?:[,.]\d+)?)\s*[- ]?\s*"
    r"(ml|l|lt|litros?|mm|cm|m|kg|g|amp(?:eres?)?|a|volts?|v|pol|polegadas?)\b",
    re.IGNORECASE,
)

NUMERO_PATTERN = re.compile(
    r"\b(?:n(?:[.\s]*[º°o])?|num\.?|numero|nr|no)\s*\.?\s*(\d+[a-z]?)\b",
    re.IGNORECASE,
)

GRAMATURA_PATTERN = re.compile(
    r"\b(?:grao|grana|gramatura)\s*\.?\s*(\d{2,4})\b",
    re.IGNORECASE,
)


def _texto_base(texto):
    texto = remover_acentos(str(texto or "")).lower()
    texto = texto.replace('"', " pol ")
    texto = texto.replace("nº", "numero")
    texto = texto.replace("n°", "numero")
    texto = texto.replace("nÂº", "numero")
    texto = texto.replace("nÂ°", "numero")
    texto = texto.replace("n?", "numero")
    texto = texto.replace("nÂ§", "numero")
    return re.sub(r"\s+", " ", texto).strip()


def _numero_float(valor):
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _formatar_numero(valor):
    if valor is None:
        return ""
    if abs(valor - int(valor)) < 0.00001:
        return str(int(valor))
    return f"{valor:.3f}".rstrip("0").rstrip(".")


def _canonical_unit(valor, unidade_raw):
    unidade_norm = remover_acentos(str(unidade_raw or "")).lower().rstrip(".")
    chave, unidade, fator = UNIT_ALIASES.get(unidade_norm, ("medida", unidade_norm, 1))
    numero = _numero_float(valor)
    if numero is None:
        return None
    valor_convertido = numero * fator
    return {
        "tipo": chave,
        "valor": _formatar_numero(valor_convertido),
        "numero": valor_convertido,
        "unidade": unidade,
        "canonico": f"{_formatar_numero(valor_convertido)}{unidade}",
    }


def unit_matcher(texto):
    """Detecta unidades tecnicas em formato canonico, sem RapidFuzz."""
    texto_base = _texto_base(texto)
    matches = []

    for match in NUMERO_PATTERN.finditer(texto_base):
        valor = match.group(1).lstrip("0") or "0"
        matches.append({
            "tipo": "numero",
            "valor": valor,
            "numero": _numero_float(valor),
            "unidade": "",
            "bruto": match.group(0),
            "canonico": f"numero {valor}",
            "span": match.span(),
        })

    for match in GRAMATURA_PATTERN.finditer(texto_base):
        valor = match.group(1)
        matches.append({
            "tipo": "gramatura",
            "valor": valor,
            "numero": _numero_float(valor),
            "unidade": "",
            "bruto": match.group(0),
            "canonico": f"gramatura {valor}",
            "span": match.span(),
        })

    for match in UNIT_PATTERN.finditer(texto_base):
        unidade = _canonical_unit(match.group(1), match.group(2))
        if not unidade:
            continue
        unidade.update({
            "bruto": match.group(0),
            "span": match.span(),
        })
        matches.append(unidade)

    matches.sort(key=lambda item: item["span"][0])
    if matches:
        logger.info(
            "[unit_matcher] texto=%r unidades=%s",
            texto,
            [
                {
                    "tipo": item["tipo"],
                    "bruto": item["bruto"],
                    "canonico": item["canonico"],
                }
                for item in matches
            ],
        )
    return matches


@lru_cache(maxsize=20000)
def canonicalizar_texto_tecnico(texto):
    texto_base = _texto_base(texto)
    matches = unit_matcher(texto_base)
    if not matches:
        return texto_base

    normalizado = texto_base
    for item in sorted(matches, key=lambda value: value["span"][0], reverse=True):
        inicio, fim = item["span"]
        normalizado = normalizado[:inicio] + f" {item['canonico']} " + normalizado[fim:]
    normalizado = re.sub(r"\s+", " ", normalizado).strip()

    if normalizado != texto_base:
        logger.info(
            "[canonical_normalization] original=%r normalizado=%r",
            texto,
            normalizado,
        )
    return normalizado
