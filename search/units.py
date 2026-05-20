from functools import lru_cache


UNIDADES_PADRAO = ["UN", "PCT", "CX", "KG", "G", "L", "ML", "PAR", "KIT"]

_MAPEAMENTO_UNIDADES = {
    "UNIDADE": "UN",
    "UNIDADES": "UN",
    "UND": "UN",
    "UNID": "UN",
    "UN": "UN",
    "PACOTE": "PCT",
    "PACOTES": "PCT",
    "PCT": "PCT",
    "CAIXA": "CX",
    "CAIXAS": "CX",
    "CX": "CX",
    "QUILOGRAMA": "KG",
    "QUILOGRAMAS": "KG",
    "KILO": "KG",
    "KILOS": "KG",
    "KG": "KG",
    "GRAMA": "G",
    "GRAMAS": "G",
    "G": "G",
    "LITRO": "L",
    "LITROS": "L",
    "L": "L",
    "MILILITRO": "ML",
    "MILILITROS": "ML",
    "ML": "ML",
    "PAR": "PAR",
    "PARES": "PAR",
    "KIT": "KIT",
    "KITS": "KIT",
}


@lru_cache(maxsize=5000)
def normalizar_unidade(valor, padrao="UN"):
    texto = str(valor or "").strip().upper()
    if not texto:
        return padrao
    texto = texto.replace(".", "").replace("-", " ").strip()
    return _MAPEAMENTO_UNIDADES.get(texto, texto or padrao)
