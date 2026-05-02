from dataclasses import asdict, dataclass
from datetime import datetime

from util import converter_numero


@dataclass
class FontePreco:
    origem: str
    descricao: str
    valor_unitario: float | None = None
    valor_total: float | None = None
    quantidade: float | None = None
    unidade: str = ""
    data_referencia: str = ""
    fornecedor_nome: str = ""
    fornecedor_cnpj: str = ""
    orgao: str = ""
    municipio: str = ""
    uf: str = ""
    link: str = ""
    evidencia: str = ""
    score: float = 0
    status_validacao: str = "pendente"
    motivos_alerta: str = ""

    def to_dict(self):
        return asdict(self)


def _primeiro(*valores):
    for valor in valores:
        if valor not in (None, ""):
            return valor
    return ""


def resultado_licitacon_para_fonte(resultado):
    return FontePreco(
        origem=resultado.get("fonte_base") or "LicitaCon",
        descricao=resultado.get("descricao", ""),
        valor_unitario=converter_numero(resultado.get("valor_unitario")),
        valor_total=converter_numero(resultado.get("valor_total")),
        quantidade=converter_numero(resultado.get("qtd")),
        unidade=resultado.get("unidade", ""),
        data_referencia=_primeiro(
            resultado.get("data_homologacao"),
            resultado.get("data"),
        ),
        fornecedor_nome=resultado.get("vencedor", ""),
        fornecedor_cnpj=resultado.get("cpf_cnpj", ""),
        orgao=resultado.get("orgao", ""),
        municipio=resultado.get("municipio_fonte", ""),
        uf="RS",
        link=resultado.get("link_licitacon", ""),
        evidencia=f"Licitacao {resultado.get('nr', '')}/{resultado.get('ano', '')}",
        score=converter_numero(resultado.get("score")) or 0,
        status_validacao="validado",
        motivos_alerta=resultado.get("avisos_tecnicos", ""),
    )


def fonte_para_resultado(fonte):
    if isinstance(fonte, FontePreco):
        fonte = fonte.to_dict()

    return {
        "score": fonte.get("score", 0),
        "modo_busca": fonte.get("origem", ""),
        "descricao": fonte.get("descricao", ""),
        "qtd": fonte.get("quantidade", ""),
        "unidade": fonte.get("unidade", ""),
        "orgao": fonte.get("orgao", ""),
        "modalidade": "",
        "nr": "",
        "ano": "",
        "objeto": "",
        "valor_unitario": fonte.get("valor_unitario", ""),
        "valor_total": fonte.get("valor_total", ""),
        "data": fonte.get("data_referencia", ""),
        "data_homologacao": fonte.get("data_referencia", ""),
        "vencedor": fonte.get("fornecedor_nome", ""),
        "cpf_cnpj": fonte.get("fornecedor_cnpj", ""),
        "link_licitacon": fonte.get("link", ""),
        "fonte_base": fonte.get("origem", ""),
        "municipio_fonte": fonte.get("municipio", ""),
        "grupo_regional": "",
        "quantidade_fora": False,
        "avisos_tecnicos": fonte.get("motivos_alerta", ""),
        "status_validacao": fonte.get("status_validacao", ""),
        "linha_csv": "",
        "evidencia": fonte.get("evidencia", ""),
    }


def fontes_para_dataframe_linhas(fontes):
    linhas = []
    for fonte in fontes:
        if isinstance(fonte, FontePreco):
            fonte = fonte.to_dict()
        linha = dict(fonte)
        linha["valor_unitario"] = converter_numero(linha.get("valor_unitario"))
        linha["valor_total"] = converter_numero(linha.get("valor_total"))
        linha["quantidade"] = converter_numero(linha.get("quantidade"))
        linhas.append(linha)
    return linhas


def agora_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
