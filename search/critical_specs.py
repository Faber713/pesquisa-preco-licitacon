import re

from utils.util import normalizar


CATEGORIAS_COM_ESPECIFICACAO_CRITICA = {
    "pincel",
    "broca",
    "agulha",
    "chave",
    "parafuso",
    "lixa",
    "cabo",
}


def detectar_especificacao_critica(texto, categoria=""):
    texto_original = str(texto or "")
    texto_norm = normalizar(texto_original)
    categoria_norm = normalizar(categoria)
    tokens = texto_norm.split()
    categoria_detectada = categoria_norm if categoria_norm in CATEGORIAS_COM_ESPECIFICACAO_CRITICA else ""
    if not categoria_detectada:
        for candidato in CATEGORIAS_COM_ESPECIFICACAO_CRITICA:
            if candidato in tokens:
                categoria_detectada = candidato
                break
    if not categoria_detectada:
        return {}

    especificacoes = []
    padroes = [
        r"\b(?:n|no|num|numero|nº)\s*\.?\s*(\d+[a-z]?)\b",
        r"\b(?:bitola|diametro|espessura|medida|tam|tamanho)\s*[:\-]?\s*(\d+(?:[,.]\d+)?\s*(?:mm|cm|m|pol|\"|awg)?)\b",
        r"\b(\d+(?:[,.]\d+)?\s*(?:mm|cm|m|pol|\"|awg))\b",
    ]
    for padrao in padroes:
        for match in re.finditer(padrao, texto_norm, re.IGNORECASE):
            valor = re.sub(r"\s+", "", match.group(1).replace(",", ".")).lower()
            especificacoes.append(valor)

    return {
        "categoria": categoria_detectada,
        "valores": list(dict.fromkeys(especificacoes)),
    }


def validar_especificacao_critica(descricao_busca, descricao_resultado, categoria=""):
    busca = detectar_especificacao_critica(descricao_busca, categoria)
    if not busca.get("valores"):
        return {"ok": True, "motivos": [], "busca": busca, "resultado": {}}

    resultado = detectar_especificacao_critica(descricao_resultado, busca.get("categoria") or categoria)
    if not resultado.get("valores"):
        return {
            "ok": False,
            "motivos": ["especificacao critica ausente"],
            "busca": busca,
            "resultado": resultado,
        }

    esperados = set(busca.get("valores") or [])
    encontrados = set(resultado.get("valores") or [])
    if esperados.intersection(encontrados):
        return {"ok": True, "motivos": [], "busca": busca, "resultado": resultado}

    return {
        "ok": False,
        "motivos": [
            "numeracao divergente"
            if busca.get("categoria") in {"pincel", "lixa"}
            else "medida critica divergente"
        ],
        "busca": busca,
        "resultado": resultado,
    }
