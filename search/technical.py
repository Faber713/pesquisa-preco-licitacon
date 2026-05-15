import logging
import re
from functools import lru_cache

from utils.normalization import normalizar_texto, remover_acentos
from search.technical_normalization import canonicalizar_texto_tecnico


logger = logging.getLogger(__name__)


STOPWORDS_TECNICAS = {
    "a",
    "alta",
    "as",
    "ao",
    "aos",
    "aproximadamente",
    "aproximado",
    "artesanato",
    "com",
    "conforme",
    "contendo",
    "cor",
    "cores",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "embalagem",
    "extra",
    "extras",
    "item",
    "lamina",
    "laminas",
    "marca",
    "material",
    "medida",
    "medindo",
    "modelo",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "premium",
    "precis",
    "precisao",
    "preciso",
    "precisos",
    "produto",
    "profissional",
    "que",
    "referencia",
    "reforcada",
    "reforcado",
    "resistencia",
    "sem",
    "super",
    "tipo",
    "un",
    "und",
    "unidade",
}

ATRIBUTOS_FRACOS = {
    "alta",
    "aproximadamente",
    "aproximado",
    "artesanato",
    "caneta",
    "contendo",
    "cortes",
    "extra",
    "extras",
    "lamina",
    "laminas",
    "medindo",
    "modelo",
    "premium",
    "precisao",
    "preciso",
    "precisos",
    "profissional",
    "reforcada",
    "reforcado",
    "resistencia",
    "super",
    "tipo",
}

EQUIVALENCIAS_TECNICAS = {
    "papel_adesivo": {
        "canonical": "papel adesivo contact",
        "terms": ("contact", "papel contact", "papel adesivo"),
        "group_tokens": ("papel", "adesivo", "contact"),
    },
    "pincel_chato": {
        "canonical": "pincel chato trincha",
        "terms": ("trincha", "pincel chato"),
        "group_tokens": ("pincel", "chato"),
    },
    "tinta_pva": {
        "canonical": "tinta pva artesanato",
        "terms": ("tinta pva", "tinta artesanato"),
        "group_tokens": ("tinta", "pva"),
    },
    "rolo": {
        "canonical": "rolo",
        "terms": ("rolinho", "mini rolo", "rolo"),
        "group_tokens": ("rolo",),
    },
}

SINONIMOS_TOKENS = {
    "bisturi": ("estilete",),
    "contact": ("papel", "adesivo"),
    "estilete": ("bisturi",),
    "rolinho": ("rolo",),
    "trincha": ("pincel", "chato"),
}

SINONIMOS_FRASES = {}
for familia, dados in EQUIVALENCIAS_TECNICAS.items():
    canonical = dados["canonical"]
    for termo in dados["terms"]:
        if normalizar_texto(termo) != normalizar_texto(canonical):
            SINONIMOS_FRASES[termo] = canonical

SUBSTANTIVOS_TECNICOS_PRIORITARIOS = {
    "adesivo",
    "bisturi",
    "bordar",
    "cetim",
    "contact",
    "crepom",
    "espuma",
    "estilete",
    "feltro",
    "fita",
    "papel",
    "pincel",
    "pva",
    "rolo",
    "rolinho",
    "tecido",
    "tinta",
    "toalha",
    "tricoline",
    "trincha",
}

CORES = {
    "amarela",
    "amarelo",
    "azul",
    "bege",
    "branca",
    "branco",
    "cinza",
    "laranja",
    "marrom",
    "preta",
    "preto",
    "rosa",
    "roxa",
    "roxo",
    "verde",
    "vermelha",
    "vermelho",
}

ATRIBUTOS_CRITICOS = {
    "amperagem",
    "capacidade",
    "espessura",
    "largura",
    "massa",
    "medida",
    "numero",
    "polegadas",
    "tensao",
    "volume",
}

TERMOS_NUMERO_CONTEXTUAL = {
    "agulha",
    "broca",
    "parafuso",
    "pincel",
}

CATEGORY_RULES = {
    "agulha": {
        "terms": {"agulha"},
        "critical": ["numero"],
    },
    "lixa": {
        "terms": {"lixa"},
        "critical": ["gramatura"],
    },
    "parafuso": {
        "terms": {"parafuso"},
        "critical": ["bitola", "comprimento", "medida", "largura"],
    },
    "pincel": {
        "terms": {"pincel", "trincha"},
        "critical": ["numero"],
    },
    "tecido": {
        "terms": {"tecido", "tricoline"},
        "critical": ["largura", "material"],
    },
    "tinta": {
        "terms": {"tinta", "pva"},
        "critical": ["volume"],
    },
}

CATEGORY_PROFILE = {
    "agulha": {
        "terms": {"agulha"},
        "rigidez": "alta",
        "score_minimo": 60,
        "aderencia_minima": 0.65,
        "hard_divergence": True,
    },
    "artesanato": {
        "terms": {"artesanato", "bisturi", "bordar", "estilete", "feltro", "eva", "pva", "toalha"},
        "rigidez": "baixa",
        "score_minimo": 30,
        "aderencia_minima": 0.15,
        "hard_divergence": False,
    },
    "decoracao": {
        "terms": {"decoracao", "decorativo", "enfeite", "estampado", "floral"},
        "rigidez": "baixa",
        "score_minimo": 30,
        "aderencia_minima": 0.15,
        "hard_divergence": False,
    },
    "escolar": {
        "terms": {"escolar", "caderno", "cartolina", "crepom", "papel", "caneta"},
        "rigidez": "baixa",
        "score_minimo": 32,
        "aderencia_minima": 0.2,
        "hard_divergence": False,
    },
    "generica": {
        "terms": set(),
        "rigidez": "media",
        "score_minimo": 35,
        "aderencia_minima": 0.3,
        "hard_divergence": False,
    },
    "lixa": {
        "terms": {"lixa"},
        "rigidez": "alta",
        "score_minimo": 60,
        "aderencia_minima": 0.6,
        "hard_divergence": True,
    },
    "papelaria": {
        "terms": {"adesivo", "contact", "crepom", "papel", "rolo"},
        "rigidez": "baixa",
        "score_minimo": 35,
        "aderencia_minima": 0.2,
        "hard_divergence": False,
    },
    "parafuso": {
        "terms": {"parafuso"},
        "rigidez": "alta",
        "score_minimo": 65,
        "aderencia_minima": 0.7,
        "hard_divergence": True,
    },
    "pincel": {
        "terms": {"pincel", "trincha"},
        "rigidez": "alta",
        "score_minimo": 58,
        "aderencia_minima": 0.6,
        "hard_divergence": True,
    },
    "tecido": {
        "terms": {"algodao", "tecido", "tricoline"},
        "rigidez": "media",
        "score_minimo": 35,
        "aderencia_minima": 0.25,
        "hard_divergence": False,
    },
    "tinta": {
        "terms": {"tinta"},
        "rigidez": "alta",
        "score_minimo": 60,
        "aderencia_minima": 0.6,
        "hard_divergence": True,
    },
}

CATEGORY_PROFILE_PRIORITY = [
    "parafuso",
    "pincel",
    "agulha",
    "tinta",
    "lixa",
    "tecido",
    "papelaria",
    "artesanato",
    "decoracao",
    "escolar",
]

TERMOS_CONSULTA_GENERICA = {
    "caneta",
    "contact",
    "feltro",
    "fita",
    "linha",
    "papel",
    "pincel",
    "rolo",
    "tecido",
    "tinta",
    "toalha",
}

TERMOS_GENERICOS_MASSIVOS = TERMOS_CONSULTA_GENERICA.union({
    "adesivo",
    "cartolina",
    "cetim",
    "crepom",
    "eva",
    "mercerizada",
    "pva",
    "tricoline",
})

TERMOS_VARIANTES = {
    "acabamento",
    "azul",
    "branca",
    "branco",
    "cinza",
    "cor",
    "cores",
    "dourada",
    "dourado",
    "estampado",
    "fosco",
    "preta",
    "preto",
    "rosa",
    "roxa",
    "roxo",
    "verde",
    "vermelha",
    "vermelho",
}

TERMOS_MATERIAL_FTS_OPCIONAL = {
    "boi",
    "pelo",
}

UNIDADES_CANONICAS = {
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
    "w": ("capacidade", "w", 1),
}


def _texto_base(texto):
    texto = canonicalizar_texto_tecnico(str(texto or ""))
    texto = remover_acentos(str(texto or "")).lower()
    texto = texto.replace("n.o", "numero")
    texto = texto.replace("nº", " numero ")
    texto = texto.replace("n°", " numero ")
    texto = texto.replace("nº", " numero ")
    texto = texto.replace("n°", " numero ")
    texto = texto.replace("n?", " numero ")
    texto = texto.replace("n§", " numero ")
    texto = texto.replace(" n ", " numero ")
    texto = texto.replace('"', " pol ")
    return re.sub(r"\s+", " ", texto).strip()


def aplicar_sinonimos_tecnicos(texto, *, expandir=False):
    texto_norm = normalizar_texto(texto)
    sinonimos = []

    for frase, equivalente in SINONIMOS_FRASES.items():
        frase_norm = normalizar_texto(frase)
        if re.search(rf"\b{re.escape(frase_norm)}\b", texto_norm):
            if equivalente not in texto_norm.split():
                texto_norm = f"{texto_norm} {equivalente}"
            sinonimos.append((frase_norm, equivalente))

    tokens = texto_norm.split()
    tokens_saida = []
    for token in tokens:
        tokens_saida.append(token)
        if expandir:
            for equivalente in SINONIMOS_TOKENS.get(token, ()):
                if equivalente not in tokens_saida:
                    tokens_saida.append(equivalente)

    if sinonimos:
        logger.debug(
            "[sinonimo_aplicado] texto=%r sinonimos=%s expandir=%s",
            texto,
            sinonimos,
            expandir,
        )
        logger.info(
            "[equivalencia_tecnica] texto=%r equivalencias=%s expandir=%s",
            texto,
            sinonimos,
            expandir,
        )

    return " ".join(dict.fromkeys(tokens_saida))


def sinonimos_aplicados_no_texto(texto):
    texto_norm = normalizar_texto(texto)
    encontrados = []
    for frase, equivalente in SINONIMOS_FRASES.items():
        frase_norm = normalizar_texto(frase)
        if re.search(rf"\b{re.escape(frase_norm)}\b", texto_norm):
            encontrados.append((frase_norm, equivalente))
    for token in texto_norm.split():
        for equivalente in SINONIMOS_TOKENS.get(token, ()):
            encontrados.append((token, equivalente))
    return list(dict.fromkeys(encontrados))


def expandir_termos_sinonimos(termos):
    expandidos = []
    for termo in termos:
        termo_norm = normalizar_texto(termo)
        if not termo_norm:
            continue
        expandidos.append(termo_norm)
        for equivalente in SINONIMOS_TOKENS.get(termo_norm, ()):
            expandidos.append(equivalente)
        frase_expandida = aplicar_sinonimos_tecnicos(termo_norm, expandir=True)
        expandidos.extend(frase_expandida.split())
    return list(dict.fromkeys(expandidos))


def remover_atributos_fracos_tokens(tokens, contexto=""):
    removidos = []
    mantidos = []
    for token in tokens:
        if token in ATRIBUTOS_FRACOS or token in STOPWORDS_TECNICAS:
            removidos.append(token)
        else:
            mantidos.append(token)
    if removidos:
        logger.info(
            "[atributo_fraco_removido] contexto=%s removidos=%s",
            contexto,
            list(dict.fromkeys(removidos)),
        )
    return mantidos


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


def _atributo(valor, unidade="", bruto=""):
    numero = _numero_float(valor)
    return {
        "valor": _formatar_numero(numero),
        "numero": numero,
        "unidade": unidade,
        "bruto": normalizar_texto(bruto or f"{valor}{unidade}"),
    }


def _adicionar_atributo(atributos, chave, valor, unidade="", bruto=""):
    if chave in atributos:
        return
    atributos[chave] = _atributo(valor, unidade, bruto)


@lru_cache(maxsize=20000)
def parse_atributos_tecnicos(texto):
    texto_canonico = canonicalizar_texto_tecnico(str(texto or ""))
    texto_expandido = aplicar_sinonimos_tecnicos(texto_canonico, expandir=True)
    texto_raw = _texto_base(texto_expandido)
    texto_norm = normalizar_texto(texto_raw)
    atributos_criticos = {}
    atributos_secundarios = {}
    spans_remover = []

    for match in re.finditer(r"\b(?:numero|num|nr|no|n)\s*\.?\s*(\d+[a-z]?)\b", texto_raw):
        numero = match.group(1)
        _adicionar_atributo(atributos_criticos, "numero", numero, "", numero)
        spans_remover.append(match.span())

    if "numero" not in atributos_criticos:
        match_tamanho = re.search(r"\b(?:tamanho|tam)\s*\.?\s*(\d{1,3}[a-z]?)\b", texto_raw)
        if match_tamanho:
            numero = match_tamanho.group(1)
            _adicionar_atributo(atributos_criticos, "numero", numero, "", numero)
            spans_remover.append(match_tamanho.span())

    padrao_medida = re.compile(
        r"\b(\d+(?:[,.]\d+)?)\s*(mm|cm|ml|m|lt|litros?|kg|g|amp(?:eres?)?|a|volts?|v|w|pol|polegadas?)\b"
    )
    for match in padrao_medida.finditer(texto_raw):
        valor, unidade_raw = match.group(1), match.group(2)
        unidade_raw = unidade_raw.rstrip(".")
        chave, unidade, fator = UNIDADES_CANONICAS.get(unidade_raw, ("medida", unidade_raw, 1))
        numero = _numero_float(valor)
        if numero is None:
            continue
        bruto = match.group(0)
        valor_convertido = numero * fator

        contexto = texto_raw[max(0, match.start() - 18): match.end() + 18]
        if unidade == "mm":
            if "bitola" in contexto:
                chave = "bitola"
            elif "comprimento" in contexto:
                chave = "comprimento"
            elif "largura" in contexto or "fita" in texto_norm or "tecido" in texto_norm:
                chave = "largura"
            elif "espessura" in contexto:
                chave = "espessura"
            elif "parafuso" in texto_norm:
                chave = "bitola"

        _adicionar_atributo(
            atributos_criticos,
            chave,
            _formatar_numero(valor_convertido),
            unidade,
            bruto,
        )
        spans_remover.append(match.span())

    if "numero" not in atributos_criticos:
        palavras_contexto = set(texto_norm.split())
        if palavras_contexto.intersection(TERMOS_NUMERO_CONTEXTUAL):
            ocupados = set()
            for inicio, fim in spans_remover:
                ocupados.update(range(inicio, fim))
            for match in re.finditer(r"\b0*(\d{1,3})\b", texto_raw):
                if any(pos in ocupados for pos in range(match.start(), match.end())):
                    continue
                numero = match.group(1)
                _adicionar_atributo(atributos_criticos, "numero", numero, "", numero)
                spans_remover.append(match.span())
                break

    if "lixa" in texto_norm and "gramatura" not in atributos_criticos:
        for match in re.finditer(r"\b(?:grana|grao|gramatura)\s*\.?\s*(\d{2,4})\b|\b(\d{2,4})\b", texto_raw):
            numero = match.group(1) or match.group(2)
            _adicionar_atributo(atributos_criticos, "gramatura", numero, "", numero)
            spans_remover.append(match.span())
            break

    cor_match = re.search(r"\bcor\s+([a-z]+)\b", texto_raw)
    if cor_match:
        cor = normalizar_texto(cor_match.group(1))
        if cor in CORES:
            atributos_secundarios["cor"] = cor
            spans_remover.append(cor_match.span())
    else:
        for match in re.finditer(r"\b([a-z]+)\b", texto_raw):
            cor = normalizar_texto(match.group(1))
            if cor in CORES:
                atributos_secundarios["cor"] = cor
                spans_remover.append(match.span())
                break

    material_match = re.search(r"\b(pelo\s+de\s+boi|100\s*%?\s*algodao|algodao|aco\s+inox|aco\s+carbono|plastico|madeira|aluminio)\b", texto_raw)
    if material_match:
        atributos_secundarios["material"] = normalizar_texto(material_match.group(1))
        spans_remover.append(material_match.span())

    texto_sem_atributos = texto_raw
    for inicio, fim in sorted(spans_remover, reverse=True):
        texto_sem_atributos = texto_sem_atributos[:inicio] + " " + texto_sem_atributos[fim:]

    tokens = []
    for token in re.findall(r"[a-z0-9]+", normalizar_texto(texto_sem_atributos)):
        if token in STOPWORDS_TECNICAS or token in ATRIBUTOS_FRACOS:
            continue
        if token.isdigit():
            continue
        if len(token) < 2:
            continue
        tokens.append(token)

    termos_principais = remover_atributos_fracos_tokens(
        list(dict.fromkeys(tokens)),
        contexto="parser",
    )
    resultado = {
        "termos_principais": termos_principais,
        "atributos_criticos": atributos_criticos,
        "atributos_secundarios": atributos_secundarios,
    }
    logger.debug("technical_parser texto=%r resultado=%s", texto, resultado)
    return resultado


def tokens_busca_tecnica(texto):
    analise = parse_atributos_tecnicos(texto)
    tokens = list(analise["termos_principais"])
    for atributo in analise["atributos_criticos"].values():
        if atributo.get("bruto"):
            tokens.append(atributo["bruto"])
        if atributo.get("valor"):
            tokens.append(atributo["valor"])
    for valor in analise["atributos_secundarios"].values():
        tokens.extend(normalizar_texto(valor).split())
    tokens = expandir_termos_sinonimos(tokens)
    return [
        token
        for token in dict.fromkeys(tokens)
        if token and token not in STOPWORDS_TECNICAS and token not in ATRIBUTOS_FRACOS
    ]


def consulta_generica(texto):
    analise = parse_atributos_tecnicos(str(texto or ""))
    termos = analise.get("termos_principais", [])
    atributos = analise.get("atributos_criticos", {})
    if atributos:
        return False
    if not termos:
        return True
    return len(termos) <= 2 and any(termo in TERMOS_CONSULTA_GENERICA for termo in termos)


def classificar_genericidade(texto):
    analise = parse_atributos_tecnicos(str(texto or ""))
    termos = analise.get("termos_principais", [])
    atributos = analise.get("atributos_criticos", {})
    termos_set = set(termos)

    if not termos:
        return "alta"

    tem_generico = bool(termos_set.intersection(TERMOS_CONSULTA_GENERICA))
    tem_massivo = bool(termos_set.intersection(TERMOS_GENERICOS_MASSIVOS))

    if tem_generico and len(termos) <= 2 and not atributos:
        return "alta"
    if tem_generico and not atributos and len(termos) <= 3:
        return "alta"
    if tem_massivo:
        return "media"
    if len(termos) <= 3 and not atributos:
        return "media"
    return "baixa"


def detectar_categoria_semantica(texto):
    analise = parse_atributos_tecnicos(str(texto or ""))
    termos = set(analise.get("termos_principais", []))
    texto_norm = normalizar_texto(texto)
    tokens_texto = set(texto_norm.split())
    universo = termos.union(tokens_texto)

    for categoria, regra in CATEGORY_RULES.items():
        if universo.intersection(regra.get("terms", set())):
            logger.info("[categoria_detectada] categoria=%s texto=%r", categoria, texto)
            return categoria
    for categoria in CATEGORY_PROFILE_PRIORITY:
        profile = CATEGORY_PROFILE.get(categoria, {})
        if categoria == "generica":
            continue
        if universo.intersection(profile.get("terms", set())):
            logger.info("[categoria_detectada] categoria=%s texto=%r", categoria, texto)
            return categoria
    logger.info("[categoria_detectada] categoria=generica texto=%r", texto)
    return "generica"


def atributos_criticos_categoria(categoria):
    return CATEGORY_RULES.get(categoria, {}).get("critical", [])


def obter_category_profile(categoria):
    profile = dict(CATEGORY_PROFILE.get(categoria) or CATEGORY_PROFILE["generica"])
    profile["categoria"] = categoria
    logger.info(
        "[categoria_profile] categoria=%s rigidez=%s score_minimo=%s aderencia_minima=%s hard_divergence=%s",
        categoria,
        profile.get("rigidez"),
        profile.get("score_minimo"),
        profile.get("aderencia_minima"),
        profile.get("hard_divergence"),
    )
    return profile


def _tokens_core_de_texto(texto):
    return [
        token
        for token in normalizar_texto(texto).split()
        if token
        and token not in STOPWORDS_TECNICAS
        and token not in ATRIBUTOS_FRACOS
        and token not in TERMOS_VARIANTES
    ]


def _limitar_tokens_core(tokens):
    tokens = list(dict.fromkeys(tokens))
    if len(tokens) <= 4:
        return tokens

    prioridade = []
    restantes = []
    for token in tokens:
        if (
            token in SUBSTANTIVOS_TECNICOS_PRIORITARIOS
            or any(ch.isdigit() for ch in token)
        ):
            prioridade.append(token)
        else:
            restantes.append(token)
    reduzidos = list(dict.fromkeys(prioridade + restantes))[:4]
    logger.info(
        "[semantic_core] limitador_explosao tokens_originais=%s tokens_reduzidos=%s",
        tokens,
        reduzidos,
    )
    return reduzidos


def _familias_equivalencia_presentes(tokens):
    tokens_set = set(tokens)
    familias = []
    for familia, dados in EQUIVALENCIAS_TECNICAS.items():
        termos = list(dados.get("terms", ())) + [dados.get("canonical", "")]
        if any(set(normalizar_texto(termo).split()).issubset(tokens_set) for termo in termos if termo):
            familias.append(familia)
    return familias


def _atributos_fracos_presentes(texto):
    tokens = normalizar_texto(texto).split()
    return list(dict.fromkeys(
        token for token in tokens if token in ATRIBUTOS_FRACOS or token in STOPWORDS_TECNICAS
    ))


def _semantic_group_key(tokens_busca, atributos_core):
    familias = _familias_equivalencia_presentes(tokens_busca)
    componentes = []
    if familias:
        componentes.extend(familias[:2])
        if familias == ["rolo"]:
            extras = [
                token for token in tokens_busca
                if token not in {"rolo", "rolinho", "mini"} and not any(ch.isdigit() for ch in token)
            ]
            componentes.extend(extras[:3])
    else:
        componentes.extend(tokens_busca[:4])

    for chave in ("volume", "massa", "largura", "bitola", "comprimento", "medida", "gramatura", "polegadas"):
        atributo = atributos_core.get(chave)
        if not isinstance(atributo, dict):
            continue
        valor = atributo.get("valor")
        unidade = atributo.get("unidade", "")
        if valor:
            componentes.append(f"{valor}{unidade}")

    componentes = [
        re.sub(r"[^a-z0-9]+", "_", normalizar_texto(str(item))).strip("_")
        for item in componentes
        if item
    ]
    return "_".join(dict.fromkeys(componentes)) or "sem_core"


@lru_cache(maxsize=20000)
def extrair_nucleo_semantico(texto):
    analise = parse_atributos_tecnicos(str(texto or ""))
    categoria = detectar_categoria_semantica(str(texto or ""))
    atributos_fracos = _atributos_fracos_presentes(str(texto or ""))
    sinonimos_usados = sinonimos_aplicados_no_texto(str(texto or ""))
    if sinonimos_usados:
        logger.info(
            "[sinonimo_aplicado] texto=%r sinonimos=%s",
            texto,
            sinonimos_usados,
        )
    tokens = list(analise.get("termos_principais", []))
    atributos_variantes = {}
    atributos_core = {}

    for chave, atributo in analise.get("atributos_criticos", {}).items():
        if chave == "numero":
            atributos_variantes[chave] = atributo
            logger.info("[variant_detected] texto=%r variante=%s valor=%s", texto, chave, atributo)
            continue
        atributos_core[chave] = atributo
        if atributo.get("bruto"):
            tokens.extend(_tokens_core_de_texto(atributo["bruto"]))
        else:
            if atributo.get("valor"):
                tokens.append(atributo["valor"])
            if atributo.get("unidade"):
                tokens.append(atributo["unidade"])

    for chave, valor in analise.get("atributos_secundarios", {}).items():
        if chave == "cor":
            atributos_variantes[chave] = valor
            logger.info("[variant_detected] texto=%r variante=%s valor=%s", texto, chave, valor)
            continue
        atributos_core[chave] = valor
        tokens.extend(_tokens_core_de_texto(valor))

    tokens_core = [
        token
        for token in tokens
        if token
        and token not in STOPWORDS_TECNICAS
        and token not in ATRIBUTOS_FRACOS
        and token not in TERMOS_VARIANTES
    ]
    tokens_core = _limitar_tokens_core(tokens_core)
    tokens_busca = [
        token
        for token in tokens_core
        if token not in TERMOS_MATERIAL_FTS_OPCIONAL
        and not token.isdigit()
        and token not in {"m", "mm", "cm", "ml", "l", "kg", "g"}
    ]
    if len(tokens_busca) < 2:
        tokens_busca = tokens_core

    core = " ".join(tokens_core)
    search_core = " ".join(tokens_busca)
    grupo_semantico = _semantic_group_key(tokens_busca, atributos_core)
    logger.info(
        "[group_key] texto=%r grupo=%r tokens=%s atributos_core=%s variantes=%s",
        texto,
        grupo_semantico,
        tokens_busca,
        atributos_core,
        list(atributos_variantes),
    )

    logger.info(
        "[semantic_core] texto=%r categoria=%s semantic_core=%r search_core=%r grupo=%r variantes=%s atributos_fracos=%s",
        texto,
        categoria,
        core,
        search_core or core,
        grupo_semantico,
        list(atributos_variantes),
        atributos_fracos,
    )

    return {
        "semantic_core": core,
        "search_core": search_core or core,
        "grupo_semantico": grupo_semantico,
        "atributos_variantes": atributos_variantes,
        "atributos_core": atributos_core,
        "atributos_fracos": atributos_fracos,
        "categoria": categoria,
        "tem_variantes": bool(atributos_variantes),
    }


def texto_sem_stopwords_tecnicas(texto):
    texto = canonicalizar_texto_tecnico(str(texto or ""))
    texto = aplicar_sinonimos_tecnicos(texto, expandir=True)
    tokens = [
        token
        for token in normalizar_texto(texto).split()
        if token not in STOPWORDS_TECNICAS and token not in ATRIBUTOS_FRACOS
    ]
    return " ".join(tokens)


def _valores_iguais(esperado, encontrado):
    if not esperado or not encontrado:
        return False
    if esperado.get("unidade") != encontrado.get("unidade"):
        return False
    n1 = esperado.get("numero")
    n2 = encontrado.get("numero")
    if n1 is None or n2 is None:
        return esperado.get("valor") == encontrado.get("valor")
    tolerancia = max(0.001, abs(n1) * 0.015)
    return abs(n1 - n2) <= tolerancia


def _atributo_equivalente(resultado_atributos, chave):
    if chave in resultado_atributos:
        return resultado_atributos.get(chave)
    equivalencias = {
        "bitola": ["medida", "largura"],
        "comprimento": ["medida", "largura"],
        "largura": ["medida", "bitola"],
        "volume": ["capacidade"],
    }
    for alternativa in equivalencias.get(chave, []):
        if alternativa in resultado_atributos:
            return resultado_atributos.get(alternativa)
    return None


def validar_compatibilidade_critica(descricao_busca, descricao_resultado):
    categoria = detectar_categoria_semantica(descricao_busca)
    profile = obter_category_profile(categoria)
    criticos = atributos_criticos_categoria(categoria)
    busca = parse_atributos_tecnicos(descricao_busca)
    resultado = parse_atributos_tecnicos(descricao_resultado)

    if not criticos:
        return {
            "ok": True,
            "categoria": categoria,
            "motivo": "",
            "atributo": "",
            "busca": busca,
            "resultado": resultado,
        }

    busca_criticos = busca.get("atributos_criticos", {})
    resultado_criticos = resultado.get("atributos_criticos", {})
    busca_sec = busca.get("atributos_secundarios", {})
    resultado_sec = resultado.get("atributos_secundarios", {})

    for atributo in criticos:
        if atributo == "material":
            esperado_material = busca_sec.get("material")
            if not esperado_material:
                continue
            encontrado_material = resultado_sec.get("material")
            if not encontrado_material:
                continue
            if esperado_material != encontrado_material:
                logger.info(
                    "[critical_divergence] categoria=%s atributo=material pesquisa=%s resultado=%s",
                    categoria,
                    esperado_material,
                    encontrado_material,
                )
                if not profile.get("hard_divergence", True):
                    return {
                        "ok": True,
                        "soft_divergence": True,
                        "categoria": categoria,
                        "motivo": "material_critico_divergente",
                        "atributo": "material",
                        "busca": busca,
                        "resultado": resultado,
                    }
                return {
                    "ok": False,
                    "soft_divergence": False,
                    "categoria": categoria,
                    "motivo": "material_critico_divergente",
                    "atributo": "material",
                    "busca": busca,
                    "resultado": resultado,
                }
            logger.info("[critical_match] categoria=%s atributo=material valor=%s", categoria, esperado_material)
            continue

        esperado = busca_criticos.get(atributo)
        if not esperado:
            continue
        encontrado = _atributo_equivalente(resultado_criticos, atributo)
        if not encontrado:
            if atributo == "numero":
                logger.info(
                    "[numero_ausente_soft] categoria=%s pesquisa=%s resultado=ausente",
                    categoria,
                    esperado.get("bruto") or esperado.get("valor"),
                )
            else:
                logger.info(
                    "[critical_missing_soft] categoria=%s atributo=%s pesquisa=%s resultado=ausente",
                    categoria,
                    atributo,
                    esperado.get("bruto") or esperado.get("valor"),
                )
            return {
                "ok": True,
                "soft_divergence": True,
                "critical_missing": True,
                "categoria": categoria,
                "motivo": f"{atributo}_critico_ausente",
                "atributo": atributo,
                "busca": busca,
                "resultado": resultado,
            }
        if not _valores_iguais(esperado, encontrado):
            if atributo == "numero":
                logger.info(
                    "[numero_divergente_hard] categoria=%s pesquisa=%s resultado=%s",
                    categoria,
                    esperado.get("bruto") or esperado.get("valor"),
                    encontrado.get("bruto") or encontrado.get("valor"),
                )
            else:
                logger.info(
                    "[critical_divergence] categoria=%s atributo=%s pesquisa=%s resultado=%s",
                    categoria,
                    atributo,
                    esperado.get("bruto") or esperado.get("valor"),
                    encontrado.get("bruto") or encontrado.get("valor"),
                )
            if not profile.get("hard_divergence", True):
                return {
                    "ok": True,
                    "soft_divergence": True,
                    "categoria": categoria,
                    "motivo": f"{atributo}_critico_divergente",
                    "atributo": atributo,
                    "busca": busca,
                    "resultado": resultado,
                }
            return {
                "ok": False,
                "soft_divergence": False,
                "categoria": categoria,
                "motivo": f"{atributo}_critico_divergente",
                "atributo": atributo,
                "busca": busca,
                "resultado": resultado,
            }
        logger.info(
            "[critical_match] categoria=%s atributo=%s valor=%s",
            categoria,
            atributo,
            esperado.get("bruto") or esperado.get("valor"),
        )

    return {
        "ok": True,
        "soft_divergence": False,
        "categoria": categoria,
        "motivo": "",
        "atributo": "",
        "busca": busca,
        "resultado": resultado,
    }


def calcular_penalidades_tecnicas(descricao_busca, descricao_resultado):
    busca = parse_atributos_tecnicos(descricao_busca)
    resultado = parse_atributos_tecnicos(descricao_resultado)
    penalidade = 0
    avisos = []

    for chave, esperado in busca["atributos_criticos"].items():
        encontrado = resultado["atributos_criticos"].get(chave)
        if not encontrado:
            penalidade_chave = 20 if chave == "numero" else 12
            penalidade += penalidade_chave
            avisos.append(
                f"{chave} ausente: pesquisa={esperado.get('bruto') or esperado.get('valor')} penalidade=-{penalidade_chave}"
            )
            continue

        if _valores_iguais(esperado, encontrado):
            continue

        if chave == "numero":
            penalidade_chave = 35
        else:
            n1 = esperado.get("numero") or 0
            n2 = encontrado.get("numero") or 0
            diferenca_relativa = abs(n1 - n2) / max(abs(n1), 1)
            penalidade_chave = min(45, max(25, int(20 + diferenca_relativa * 30)))

        penalidade += penalidade_chave
        avisos.append(
            f"{chave} divergente: pesquisa={esperado.get('bruto') or esperado.get('valor')} "
            f"resultado={encontrado.get('bruto') or encontrado.get('valor')} penalidade=-{penalidade_chave}"
        )

    return {
        "penalidade": min(80, penalidade),
        "avisos": avisos,
        "busca": busca,
        "resultado": resultado,
    }
