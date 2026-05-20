from enum import Enum


class FontePesquisa(Enum):
    LICITACON = "licitacon"
    PNCP = "pncp"
    COMPRASGOV = "comprasgov"
    INTERNET = "internet"
    FORNECEDORES = "fornecedores"


SOURCE_RELIABILITY = {
    FontePesquisa.LICITACON.value: 1.00,
    FontePesquisa.PNCP.value: 0.95,
    FontePesquisa.COMPRASGOV.value: 0.90,
    FontePesquisa.FORNECEDORES.value: 0.75,
    FontePesquisa.INTERNET.value: 0.60,
}

PROVIDERS_ATIVOS = {
    FontePesquisa.LICITACON.value: True,
    FontePesquisa.PNCP.value: True,
    FontePesquisa.COMPRASGOV.value: False,
    FontePesquisa.INTERNET.value: False,
    FontePesquisa.FORNECEDORES.value: False,
}

SOURCE_LABELS = {
    FontePesquisa.LICITACON.value: "LicitaCon RS",
    FontePesquisa.PNCP.value: "PNCP",
    FontePesquisa.COMPRASGOV.value: "Compras.gov",
    FontePesquisa.INTERNET.value: "Internet",
    FontePesquisa.FORNECEDORES.value: "Fornecedores",
}

SOURCE_ALIASES = {
    "todos": "todos",
    "all": "todos",
    "licitacon": FontePesquisa.LICITACON.value,
    "licitacon_rs": FontePesquisa.LICITACON.value,
    "pncp": FontePesquisa.PNCP.value,
    "compras.gov": FontePesquisa.COMPRASGOV.value,
    "comprasgov": FontePesquisa.COMPRASGOV.value,
    "internet": FontePesquisa.INTERNET.value,
    "fornecedor": FontePesquisa.FORNECEDORES.value,
    "fornecedores": FontePesquisa.FORNECEDORES.value,
}


def fontes_disponiveis():
    return [fonte.value for fonte in FontePesquisa]


def normalizar_fontes(fontes):
    selecionadas = []
    for fonte in fontes or []:
        valor = SOURCE_ALIASES.get(str(fonte or "").strip().lower())
        if valor == "todos":
            return fontes_disponiveis()
        if valor and valor not in selecionadas:
            selecionadas.append(valor)
    return selecionadas or [FontePesquisa.LICITACON.value]


def fonte_confiabilidade(fonte):
    return SOURCE_RELIABILITY.get(str(fonte or "").lower(), 0.50)


def fonte_rotulo(fonte):
    return SOURCE_LABELS.get(str(fonte or "").lower(), str(fonte or ""))


def provider_ativo(fonte):
    return PROVIDERS_ATIVOS.get(str(fonte or "").lower(), False)


def filtrar_fontes_ativas(fontes):
    return [fonte for fonte in normalizar_fontes(fontes) if provider_ativo(fonte)]
