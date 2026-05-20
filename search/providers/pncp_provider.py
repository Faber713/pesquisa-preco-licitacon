import logging
import time
from dataclasses import dataclass

from rapidfuzz import fuzz

from config.runtime_settings import (
    PNCP_MAX_CONTRATACOES,
    PNCP_MAX_ITENS_PRE_SCORE,
    PNCP_MAX_ITENS_SCORE,
)
from search.models import SearchResult, item_valido
from search.providers.base_provider import BaseProvider
from search.score import calcular_score
from search.intelligence import (
    calcular_score_final_inteligente,
    quantity_similarity_score,
    quantidade_desejada,
    recency_score,
    semantic_category_match,
    source_priority_score,
)
from services.pncp_client import PNCPClient, PNCPClientError
from utils.util import converter_numero, normalizar, palavras_fortes, termos_compativeis


logger = logging.getLogger("pncp")

PNCP_SCORE_MINIMO = 58
PNCP_MIN_TERMOS_FORTES = 1
TERMOS_PNCP_GENERICOS = {
    "aquisicao",
    "contratacao",
    "servico",
    "servicos",
    "material",
    "materiais",
    "produto",
    "produtos",
    "item",
    "itens",
    "fornecimento",
    "equipamento",
    "equipamentos",
    "diversos",
    "generico",
}


@dataclass(frozen=True)
class PncpCompraRef:
    cnpj: str
    ano: int
    sequencial: str
    registro: dict


def _lista_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for chave in ("data", "items", "itens", "resultados"):
            valor = payload.get(chave)
            if isinstance(valor, list):
                return valor
    return []


def calcular_score_pncp(descricao_busca, descricao_item, criterios=None):
    criterios = criterios or {}
    categoria = semantic_category_match(descricao_busca, descricao_item, criterios)
    if not categoria["ok"]:
        return {
            "score": 0,
            "aprovado": False,
            "motivos_descarte": [categoria["motivo"]],
            "termos_fortes_encontrados": [],
            "obrigatorios_encontrados": [],
            "score_texto": 0,
            "categoria": categoria,
        }
    score_info = calcular_score(descricao_busca, descricao_item, criterios, modo="rigido")
    busca_norm = normalizar(descricao_busca)
    item_norm = normalizar(descricao_item)
    token_set = fuzz.token_set_ratio(busca_norm, item_norm)
    fortes_busca = [
        termo
        for termo in palavras_fortes(descricao_busca)
        if termo not in TERMOS_PNCP_GENERICOS
    ]
    fortes_encontrados = [
        termo for termo in fortes_busca if termos_compativeis(termo, item_norm)
    ]
    obrigatorios = [
        normalizar(termo)
        for termo in criterios.get("termos_obrigatorios", [])
        if normalizar(termo) and normalizar(termo) not in TERMOS_PNCP_GENERICOS
    ]
    obrigatorios_encontrados = [
        termo for termo in obrigatorios if termos_compativeis(termo, item_norm)
    ]

    proporcao_fortes = len(fortes_encontrados) / len(fortes_busca) if fortes_busca else 0
    proporcao_obrigatorios = (
        len(obrigatorios_encontrados) / len(obrigatorios) if obrigatorios else 1
    )
    score = (
        score_info.get("score", 0) * 0.55
        + token_set * 0.20
        + proporcao_fortes * 100 * 0.20
        + proporcao_obrigatorios * 100 * 0.05
    )

    motivos_descarte = []
    if fortes_busca and len(fortes_encontrados) < PNCP_MIN_TERMOS_FORTES:
        score -= 35
        motivos_descarte.append("sem_termo_forte")
    if obrigatorios and not obrigatorios_encontrados:
        score -= 20
        motivos_descarte.append("sem_obrigatorio")
    if len([p for p in item_norm.split() if p not in TERMOS_PNCP_GENERICOS]) < 2:
        score -= 25
        motivos_descarte.append("descricao_generica")

    score = round(max(0, min(100, score)), 2)
    aprovado = score >= PNCP_SCORE_MINIMO and not motivos_descarte
    return {
        "score": score,
        "aprovado": aprovado,
        "motivos_descarte": motivos_descarte,
        "termos_fortes_encontrados": fortes_encontrados,
        "obrigatorios_encontrados": obrigatorios_encontrados,
        "score_texto": round(token_set, 2),
        "categoria": categoria,
    }


class PNCPProvider(BaseProvider):
    nome = "pncp"
    confiabilidade = 0.95

    def __init__(self, client=None):
        self.client = client or PNCPClient()
        self.last_stats = {}

    @staticmethod
    def _primeiro(*valores):
        for valor in valores:
            if valor not in (None, ""):
                return valor
        return ""

    @staticmethod
    def _data(valor):
        return str(valor or "")[:10]

    @staticmethod
    def _link_contratacao(registro):
        link = registro.get("linkSistemaOrigem") or registro.get("linkProcessoEletronico")
        if link:
            return link
        cnpj = (registro.get("orgaoEntidade") or {}).get("cnpj")
        ano = registro.get("anoCompra")
        sequencial = registro.get("sequencialCompra")
        if cnpj and ano and sequencial:
            return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
        return "https://pncp.gov.br/app/editais"

    @staticmethod
    def _texto_contratacao(registro):
        orgao = registro.get("orgaoEntidade") or {}
        unidade = registro.get("unidadeOrgao") or {}
        return " ".join(
            str(parte or "")
            for parte in [
                registro.get("objetoCompra"),
                registro.get("informacaoComplementar"),
                registro.get("modalidadeNome"),
                orgao.get("razaoSocial"),
                unidade.get("nomeUnidade"),
                unidade.get("municipioNome"),
            ]
        )

    @staticmethod
    def _descricao_item(item):
        return item.get("descricao") or item.get("descricaoItem") or item.get("nome") or ""

    @staticmethod
    def _termos(descricao):
        termos = palavras_fortes(descricao)
        return [termo for termo in termos if len(termo) >= 3]

    def _termos_pre_filtro(self, descricao, criterios):
        criterios = criterios or {}
        termos = []
        termos.extend(criterios.get("frases_chave", []) or [])
        termos.extend(criterios.get("termos_obrigatorios", []) or [])
        termos.extend(self._termos(descricao))
        normalizados = []
        for termo in termos:
            termo_norm = normalizar(termo)
            if termo_norm and termo_norm not in TERMOS_PNCP_GENERICOS:
                normalizados.append(termo_norm)
        return list(dict.fromkeys(normalizados))

    def _contratacao_pre_filtrada(self, registro, descricao, criterios):
        return True

    def _compra_ref(self, registro):
        orgao = registro.get("orgaoEntidade") or {}
        cnpj = orgao.get("cnpj")
        ano = converter_numero(registro.get("anoCompra"))
        sequencial = registro.get("sequencialCompra")
        if not cnpj or not ano or not sequencial:
            return None
        return PncpCompraRef(str(cnpj), int(ano), str(sequencial), registro)

    def _pre_filtrar_item(self, item, descricao, criterios):
        texto = self._descricao_item(item)
        texto_norm = normalizar(texto)
        if len(texto_norm) < 6:
            return False, "descricao_curta"
        termos = self._termos_pre_filtro(descricao, criterios)
        if not termos:
            return True, ""
        if any(termos_compativeis(termo, texto_norm) for termo in termos):
            return True, ""
        return False, "sem_termo_pre_filtro"

    def _resultados_do_item(self, compra_ref, item):
        numero_item = item.get("numeroItem")
        if not numero_item:
            return []
        try:
            return _lista_payload(
                self.client.listar_resultados_item(
                    compra_ref.cnpj,
                    compra_ref.ano,
                    compra_ref.sequencial,
                    numero_item,
                )
            )
        except PNCPClientError:
            return []

    def _normalizar_item(self, item, compra_ref, descricao_busca, score_info, criterios=None):
        registro = compra_ref.registro
        orgao = registro.get("orgaoEntidade") or {}
        unidade_orgao = registro.get("unidadeOrgao") or {}
        resultados_item = self._resultados_do_item(compra_ref, item)
        resultado_homologado = resultados_item[0] if resultados_item else {}

        valor = converter_numero(
            self._primeiro(
                resultado_homologado.get("valorUnitarioHomologado"),
                resultado_homologado.get("valorUnitario"),
                item.get("valorUnitarioHomologado"),
                item.get("valorUnitarioEstimado"),
            )
        )
        valor_total = converter_numero(
            self._primeiro(
                resultado_homologado.get("valorTotalHomologado"),
                resultado_homologado.get("valorTotal"),
                item.get("valorTotal"),
            )
        )
        quantidade = converter_numero(item.get("quantidade"))
        descricao = self._descricao_item(item) or descricao_busca
        fornecedor = self._primeiro(
            resultado_homologado.get("nomeRazaoSocialFornecedor"),
            resultado_homologado.get("fornecedorNome"),
            resultado_homologado.get("razaoSocialFornecedor"),
        )
        fornecedor_cnpj = self._primeiro(
            resultado_homologado.get("niFornecedor"),
            resultado_homologado.get("cnpjFornecedor"),
        )
        data_ref = self._data(
            self._primeiro(
                resultado_homologado.get("dataResultado"),
                registro.get("dataAtualizacaoGlobal"),
                registro.get("dataAtualizacao"),
                registro.get("dataPublicacaoPncp"),
            )
        )
        ano_ref = converter_numero(registro.get("anoCompra")) or converter_numero(str(data_ref)[:4])
        link = self._link_contratacao(registro)
        score_quantidade = quantity_similarity_score(quantidade, quantidade_desejada(criterios=criterios))
        score_recencia = recency_score(data_ref, ano_ref)
        score_fonte = source_priority_score("PNCP")
        categoria = score_info.get("categoria") or {}
        score_final = calcular_score_final_inteligente(
            score_textual=score_info.get("score", 0),
            score_categoria=categoria.get("score", 80),
            score_quantidade=score_quantidade,
            score_tecnico=100,
            score_recencia=score_recencia,
            score_fonte=score_fonte,
        )
        metadados = {
            "item_descartado": not score_info.get("aprovado"),
            "score_pncp": score_info,
            "contratacao": registro,
            "item": item,
            "resultados_item": resultados_item,
        }
        base = SearchResult(
            fonte="PNCP",
            descricao=descricao,
            valor_unitario=valor or 0,
            unidade=item.get("unidadeMedida", ""),
            fornecedor=fornecedor,
            orgao=orgao.get("razaoSocial", ""),
            data=data_ref,
            score=score_final,
            url=link,
            metadados=metadados,
        ).to_dict()
        base.update(
            {
                "valor_unitario": valor,
                "valor_total": valor_total,
                "vencedor": fornecedor,
                "fornecedor_cnpj": fornecedor_cnpj,
                "cpf_cnpj": fornecedor_cnpj,
                "fonte_base": "PNCP",
                "ano": int(ano_ref) if ano_ref else "",
                "link_licitacon": link,
                "quantidade": quantidade,
                "qtd": quantidade,
                "modalidade": registro.get("modalidadeNome", ""),
                "data_homologacao": data_ref,
                "municipio_fonte": unidade_orgao.get("municipioNome", ""),
                "uf": unidade_orgao.get("ufSigla", ""),
                "nr": registro.get("numeroCompra", ""),
                "processo": registro.get("processo", ""),
                "objeto": registro.get("objetoCompra", ""),
                "modo_busca": "pncp",
                "quantidade_fora": False,
                "avisos_tecnicos": "PNCP score rigido",
                "score_textual": score_info.get("score", 0),
                "score_quantidade": score_quantidade,
                "fonte_prioridade": score_fonte,
                "compatibilidade_categoria": categoria,
                "compatibility_reasons": list(categoria.get("compatibility_reasons") or []),
                "rejection_reasons": list(categoria.get("rejection_reasons") or []),
                "categoria_detectada": categoria.get("categoria_detectada"),
                "score_final_componentes": {
                    "score_textual": score_info.get("score", 0),
                    "score_categoria": categoria.get("score", 80),
                    "score_quantidade": score_quantidade,
                    "score_tecnico": 100,
                    "score_recencia": score_recencia,
                    "score_fonte": score_fonte,
                },
                "score_details": {
                    "score_textual": score_info.get("score", 0),
                    "score_categoria": categoria.get("score", 80),
                    "score_quantidade": score_quantidade,
                    "score_tecnico": 100,
                    "score_recencia": score_recencia,
                    "score_fonte": score_fonte,
                },
                "compatibilidade_status": "VALIDO",
                "item_descartado": metadados["item_descartado"],
                "raw": metadados,
            }
        )
        return base

    def _pipeline_itens(self, registros, descricao, criterios, limite):
        inicio = time.perf_counter()
        tempo_refs = 0
        tempo_itens = 0
        tempo_score = 0
        stats = {
            "contratacoes": len(registros),
            "contratacoes_filtradas": 0,
            "itens_total": 0,
            "itens_pre_filtrados": 0,
            "itens_scorados": 0,
            "itens_descartados": 0,
            "itens_validos": 0,
        }
        normalizados = []

        inicio_refs = time.perf_counter()
        refs = []
        for registro in registros:
            if not self._contratacao_pre_filtrada(registro, descricao, criterios):
                continue
            compra_ref = self._compra_ref(registro)
            if compra_ref:
                refs.append(compra_ref)
            if len(refs) >= PNCP_MAX_CONTRATACOES:
                break
        tempo_refs = round((time.perf_counter() - inicio_refs) * 1000, 2)
        stats["contratacoes_filtradas"] = len(refs)

        for compra_ref in refs:
            inicio_itens = time.perf_counter()
            try:
                itens = _lista_payload(
                    self.client.listar_itens_compra(
                        compra_ref.cnpj,
                        compra_ref.ano,
                        compra_ref.sequencial,
                    )
                )
            except PNCPClientError:
                itens = []
            tempo_itens += (time.perf_counter() - inicio_itens) * 1000
            stats["itens_total"] += len(itens)

            for item in itens:
                if stats["itens_pre_filtrados"] >= PNCP_MAX_ITENS_PRE_SCORE:
                    break
                aprovado_pre, motivo_pre = self._pre_filtrar_item(item, descricao, criterios)
                if not aprovado_pre:
                    stats["itens_descartados"] += 1
                    logger.debug(
                        "PNCP item_pre_descartado descricao_busca=%r descricao_item=%r motivo=%s",
                        descricao,
                        self._descricao_item(item),
                        motivo_pre,
                    )
                    continue
                stats["itens_pre_filtrados"] += 1

                if stats["itens_scorados"] >= PNCP_MAX_ITENS_SCORE:
                    break
                inicio_score = time.perf_counter()
                score_info = calcular_score_pncp(descricao, self._descricao_item(item), criterios)
                tempo_score += (time.perf_counter() - inicio_score) * 1000
                stats["itens_scorados"] += 1
                if not score_info["aprovado"]:
                    stats["itens_descartados"] += 1
                    logger.debug(
                        "PNCP item_descartado descricao_busca=%r descricao_item=%r score=%s motivos=%s",
                        descricao,
                        self._descricao_item(item),
                        score_info["score"],
                        score_info["motivos_descarte"],
                    )
                    continue

                normalizado = self._normalizar_item(item, compra_ref, descricao, score_info, criterios)
                if normalizado.get("valor") and item_valido(normalizado):
                    normalizados.append(normalizado)
                    stats["itens_validos"] += 1
                if len(normalizados) >= limite:
                    break
            if len(normalizados) >= limite:
                break
            if stats["itens_pre_filtrados"] >= PNCP_MAX_ITENS_PRE_SCORE:
                break
            if stats["itens_scorados"] >= PNCP_MAX_ITENS_SCORE:
                break

        resultados = sorted(
            [item for item in normalizados if item_valido(item)],
            key=lambda r: r.get("score", 0),
            reverse=True,
        )
        stats.update(
            {
                "tempo_total_ms": round((time.perf_counter() - inicio) * 1000, 2),
                "tempo_refs_ms": round(tempo_refs, 2),
                "tempo_itens_ms": round(tempo_itens, 2),
                "tempo_score_ms": round(tempo_score, 2),
                "resultados": len(resultados),
                "score_max": max([r.get("score", 0) for r in resultados] or [0]),
                "score_min": min([r.get("score", 0) for r in resultados] or [0]),
            }
        )
        self.last_stats = stats
        logger.debug(
            "PNCP pipeline descricao=%r contratacoes=%s contratacoes_filtradas=%s itens_total=%s itens_pre_filtrados=%s itens_scorados=%s itens_validos=%s itens_descartados=%s tempo_total_ms=%s tempo_refs_ms=%s tempo_itens_ms=%s tempo_score_ms=%s",
            descricao,
            stats["contratacoes"],
            stats["contratacoes_filtradas"],
            stats["itens_total"],
            stats["itens_pre_filtrados"],
            stats["itens_scorados"],
            stats["itens_validos"],
            stats["itens_descartados"],
            stats["tempo_total_ms"],
            stats["tempo_refs_ms"],
            stats["tempo_itens_ms"],
            stats["tempo_score_ms"],
        )
        return resultados

    def converter_resultados(self, registros, descricao, criterios=None, limite=20):
        return self._pipeline_itens(registros, descricao, criterios or {}, limite)

    def buscar(
        self,
        descricao,
        *,
        criterios=None,
        limite=20,
        dias=180,
        modalidades=(8, 6, 7, 9, 5),
        max_paginas=1,
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
    ):
        inicio = time.perf_counter()
        self.last_stats = {}
        try:
            registros = self.client.buscar_contratacoes(
                dias=dias,
                modalidades=modalidades,
                max_paginas=max_paginas,
                uf=uf,
                codigo_municipio_ibge=codigo_municipio_ibge,
                cnpj=cnpj,
            )
            resultados = self.converter_resultados(
                registros,
                descricao,
                criterios=criterios,
                limite=limite,
            )
            logger.debug(
                "PNCP provider descricao=%r registros=%s resultados=%s tempo_ms=%s score_max=%s score_min=%s",
                descricao,
                len(registros),
                len(resultados),
                round((time.perf_counter() - inicio) * 1000, 2),
                max([r.get("score", 0) for r in resultados] or [0]),
                min([r.get("score", 0) for r in resultados] or [0]),
            )
            return resultados
        except PNCPClientError as erro:
            logger.warning("PNCP provider indisponivel descricao=%r erro=%s", descricao, erro)
            return []
