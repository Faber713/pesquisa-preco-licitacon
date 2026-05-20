from utils.util import converter_numero


def normalizar_resultado_internet(item):
    return {
        "descricao": item.get("descricao", ""),
        "valor": converter_numero(item.get("valor")),
        "fornecedor": item.get("fornecedor", ""),
        "orgao": item.get("orgao", ""),
        "fonte": "Internet",
        "ano": item.get("ano", ""),
        "link_origem": item.get("link", ""),
        "score": item.get("score", 0),
        "quantidade": item.get("quantidade", ""),
        "modalidade": item.get("modalidade", ""),
        "data": item.get("data", ""),
        "unidade": item.get("unidade", ""),
        "raw": item,
    }
