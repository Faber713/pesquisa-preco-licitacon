import json
from datetime import datetime

from collectors.pncp.dedup import hash_item_pncp
from utils.util import converter_numero, normalizar


def agora_iso():
    return datetime.now().isoformat(timespec="seconds")


def primeiro(registro, *chaves, padrao=""):
    for chave in chaves:
        valor = registro.get(chave)
        if valor not in (None, ""):
            return valor
    return padrao


def numero_controle(registro):
    return primeiro(
        registro,
        "numeroControlePNCP",
        "numeroControlePNCPCompra",
        "numeroControle",
    )


def normalizar_contratacao(registro):
    orgao = registro.get("orgaoEntidade") or {}
    unidade = registro.get("unidadeOrgao") or {}
    amparo = registro.get("amparoLegal") or {}
    agora = agora_iso()
    controle = numero_controle(registro)
    if not controle:
        controle = "|".join(
            str(parte or "")
            for parte in [
                orgao.get("cnpj", ""),
                registro.get("anoCompra", ""),
                registro.get("sequencialCompra", ""),
            ]
        )
    return {
        "numero_controle_pncp": controle,
        "cnpj_orgao": orgao.get("cnpj", ""),
        "orgao": orgao.get("razaoSocial", ""),
        "municipio": unidade.get("municipioNome", ""),
        "uf": unidade.get("ufSigla", ""),
        "ano_compra": converter_numero(registro.get("anoCompra")),
        "sequencial_compra": registro.get("sequencialCompra", ""),
        "modalidade": registro.get("modalidadeNome", ""),
        "srp": 1 if registro.get("srp") or registro.get("sistemaRegistroPrecos") else 0,
        "objeto_compra": registro.get("objetoCompra", ""),
        "informacao_complementar": registro.get("informacaoComplementar", ""),
        "data_publicacao": primeiro(registro, "dataPublicacaoPncp", "dataPublicacao"),
        "data_atualizacao": primeiro(registro, "dataAtualizacaoGlobal", "dataAtualizacao"),
        "valor_estimado": converter_numero(
            primeiro(registro, "valorTotalEstimado", "valorEstimado", "valorTotal")
        ),
        "valor_homologado": converter_numero(
            primeiro(registro, "valorTotalHomologado", "valorHomologado")
        ),
        "link_origem": primeiro(registro, "linkSistemaOrigem", "linkProcessoEletronico"),
        "usuario_nome": registro.get("usuarioNome", ""),
        "amparo_legal_json": json.dumps(amparo, ensure_ascii=False),
        "raw_json": json.dumps(registro, ensure_ascii=False),
        "coletado_em": agora,
        "atualizado_em": agora,
    }


def normalizar_item(item, contratacao_id, contratacao):
    descricao = item.get("descricao") or item.get("descricaoItem") or item.get("nome") or ""
    numero_item = item.get("numeroItem")
    numero = contratacao.get("numero_controle_pncp") or ""
    return {
        "contratacao_id": contratacao_id,
        "numero_item": converter_numero(numero_item),
        "descricao_original": descricao,
        "descricao_normalizada": normalizar(descricao),
        "unidade": item.get("unidadeMedida", ""),
        "quantidade": converter_numero(item.get("quantidade")),
        "valor_estimado_unitario": converter_numero(
            primeiro(item, "valorUnitarioEstimado", "valorUnitario", "valorEstimado")
        ),
        "valor_estimado_total": converter_numero(
            primeiro(item, "valorTotal", "valorTotalEstimado")
        ),
        "valor_homologado_unitario": converter_numero(
            primeiro(item, "valorUnitarioHomologado", "valorHomologado")
        ),
        "fornecedor_nome": primeiro(
            item,
            "nomeRazaoSocialFornecedor",
            "fornecedorNome",
            "razaoSocialFornecedor",
        ),
        "fornecedor_cnpj": primeiro(item, "niFornecedor", "cnpjFornecedor"),
        "categoria": "",
        "subcategoria": "",
        "raw_json": json.dumps(item, ensure_ascii=False),
        "hash_dedup": hash_item_pncp(numero, numero_item, descricao),
    }
