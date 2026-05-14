import json
import os
import re
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from datetime import date, datetime, timedelta

import requests
from rapidfuzz import fuzz

from storage.app_storage import listar_cotacoes_por_descricao
from search.fontes_preco import FontePreco, agora_iso
from utils.util import converter_numero, normalizar, palavras_fortes, termos_compativeis


PNCP_BASE_URL = "https://pncp.gov.br/api/consulta"
PNCP_DADOS_URL = "https://pncp.gov.br/api/pncp"
PNCP_MODALIDADES_PADRAO = [8, 6, 7, 9, 5]
PNCP_MIN_SCORE_CONTRATACAO_DETALHE = 35
PNCP_MAX_CONTRATACOES_DETALHADAS = 80
PNCP_TERMOS_FRACOS = {
    "referencia",
    "referente",
    "modelo",
    "marca",
    "tipo",
    "medida",
    "tamanho",
}
PNCP_CANDIDATOS_POR_TERMO = {
    "alicate": ["ferramenta", "ferramentas", "eletrico", "eletricos", "eletrica", "eletricas", "medicao", "instrumento", "instrumentos"],
    "amperimetro": ["ferramenta", "ferramentas", "eletrico", "eletricos", "eletrica", "eletricas", "medicao", "instrumento", "instrumentos"],
    "multimetro": ["ferramenta", "ferramentas", "eletrico", "eletricos", "eletrica", "eletricas", "medicao", "instrumento", "instrumentos"],
    "voltimetro": ["ferramenta", "ferramentas", "eletrico", "eletricos", "eletrica", "eletricas", "medicao", "instrumento", "instrumentos"],
    "crimpar": ["ferramenta", "ferramentas", "eletrico", "eletricos", "eletrica", "eletricas", "terminais", "conectores"],
    "terminal": ["eletrico", "eletricos", "eletrica", "eletricas", "terminais", "conectores"],
    "terminais": ["eletrico", "eletricos", "eletrica", "eletricas", "conectores"],
}


def _carregar_env_local():
    if not os.path.exists(".env"):
        return
    try:
        with open(".env", "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
    except OSError:
        pass


_carregar_env_local()


def _abrir_json(url, timeout=20, tentativas=3):
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 pesquisa-preco-licitacon/1.0",
    }
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.get(url, headers=headers, timeout=(5, timeout))
            resposta.raise_for_status()
            return resposta.json()
        except requests.RequestException as erro:
            ultimo_erro = erro
            if tentativa < tentativas:
                time.sleep(0.6 * tentativa)
    raise ultimo_erro


@lru_cache(maxsize=256)
def _abrir_json_cache(url, timeout=20):
    return _abrir_json(url, timeout=timeout)


def _texto_preco_para_float(texto):
    if not texto:
        return None
    match = re.search(r"R\$\s*[\d.]+,\d{2}", texto)
    if not match:
        match = re.search(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", texto)
    return converter_numero(match.group(0)) if match else None


def _data_pncp(valor):
    if not valor:
        return ""
    texto = str(valor)
    return texto[:10]


def _listar_itens_pncp(registro, timeout=15):
    orgao = registro.get("orgaoEntidade") or {}
    cnpj = orgao.get("cnpj")
    ano = registro.get("anoCompra")
    sequencial = registro.get("sequencialCompra")
    if not cnpj or not ano or not sequencial:
        return []

    url = f"{PNCP_DADOS_URL}/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
    dados = _abrir_json_cache(url, timeout=timeout)
    return dados if isinstance(dados, list) else []


def _listar_resultados_item_pncp(registro, numero_item, timeout=15):
    orgao = registro.get("orgaoEntidade") or {}
    cnpj = orgao.get("cnpj")
    ano = registro.get("anoCompra")
    sequencial = registro.get("sequencialCompra")
    if not cnpj or not ano or not sequencial or not numero_item:
        return []

    url = (
        f"{PNCP_DADOS_URL}/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}"
        f"/itens/{numero_item}/resultados"
    )
    dados = _abrir_json_cache(url, timeout=timeout)
    return dados if isinstance(dados, list) else []


def _registro_pncp_candidato(registro, busca_norm, termos):
    objeto = str(registro.get("objetoCompra", ""))
    unidade = registro.get("unidadeOrgao") or {}
    orgao = registro.get("orgaoEntidade") or {}
    texto_contratacao = " ".join([
        objeto,
        str(registro.get("informacaoComplementar", "")),
        str(unidade.get("nomeUnidade", "")),
        str(unidade.get("municipioNome", "")),
        str(orgao.get("razaoSocial", "")),
        str(registro.get("modalidadeNome", "")),
    ])
    texto_norm = normalizar(texto_contratacao)
    score = fuzz.token_set_ratio(busca_norm, texto_norm)
    tem_termo = any(termos_compativeis(termo, texto_norm) for termo in termos)
    return texto_contratacao, score, tem_termo


def _registro_do_municipio(registro, municipio):
    if not municipio:
        return False

    municipio_norm = normalizar(municipio)
    unidade = registro.get("unidadeOrgao") or {}
    orgao = registro.get("orgaoEntidade") or {}
    textos = [
        unidade.get("municipioNome", ""),
        unidade.get("nomeUnidade", ""),
        orgao.get("razaoSocial", ""),
    ]
    return any(municipio_norm in normalizar(texto) for texto in textos)


def _termos_pncp(descricao_busca):
    termos = [
        termo
        for termo in palavras_fortes(descricao_busca)
        if termo not in PNCP_TERMOS_FRACOS
    ]
    return list(dict.fromkeys(termos))


def _termos_candidatos_pncp(termos, ampliar=False):
    if not ampliar:
        return termos

    termos_candidatos = list(termos)
    for termo in termos:
        termos_candidatos.extend(PNCP_CANDIDATOS_POR_TERMO.get(termo, []))
    return list(dict.fromkeys(termos_candidatos))


def _termos_encontrados_pncp(termos, texto_norm):
    return [
        termo
        for termo in termos
        if termos_compativeis(termo, texto_norm)
    ]


def _item_pncp_compativel(descricao_item, busca_norm, termos):
    texto_norm = normalizar(descricao_item)
    score = fuzz.token_set_ratio(busca_norm, texto_norm)
    termos_encontrados = _termos_encontrados_pncp(termos, texto_norm)

    if termos:
        minimo_termos = 2 if len(termos) >= 3 else 1
        return len(termos_encontrados) >= minimo_termos, score, termos_encontrados

    return score >= 75, score, termos_encontrados


def _fonte_contratacao_pncp(registro, descricao_busca, score_contratacao):
    unidade = registro.get("unidadeOrgao") or {}
    orgao = registro.get("orgaoEntidade") or {}
    valor = converter_numero(registro.get("valorTotalHomologado")) or converter_numero(registro.get("valorTotalEstimado"))
    if not valor:
        return None

    return FontePreco(
        origem="PNCP",
        descricao=registro.get("objetoCompra") or descricao_busca,
        valor_unitario=valor,
        valor_total=valor,
        quantidade=None,
        unidade="contratacao",
        data_referencia=_data_pncp(registro.get("dataAtualizacaoGlobal") or registro.get("dataPublicacaoPncp")),
        fornecedor_nome="",
        fornecedor_cnpj="",
        orgao=orgao.get("razaoSocial", ""),
        municipio=unidade.get("municipioNome", ""),
        uf=unidade.get("ufSigla", ""),
        link=_link_pncp(registro),
        evidencia=(
            f"PNCP contratacao {registro.get('anoCompra', '')}/"
            f"{registro.get('sequencialCompra', '')}; valor total da contratacao."
        ),
        score=round(score_contratacao, 2),
        status_validacao="revisao obrigatoria",
        motivos_alerta=(
            "Valor total da contratacao PNCP usado como fallback porque o item detalhado "
            "nao foi localizado ou nao retornou preco unitario. Conferir antes de usar."
        ),
    )


def _link_pncp(registro):
    orgao = registro.get("orgaoEntidade") or {}
    cnpj = orgao.get("cnpj")
    ano = registro.get("anoCompra")
    sequencial = registro.get("sequencialCompra")
    return (
        registro.get("linkSistemaOrigem")
        or registro.get("linkProcessoEletronico")
        or (
            f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
            if cnpj and ano and sequencial
            else ""
        )
    )


def buscar_pncp(
    descricao_busca,
    limite=20,
    dias=60,
    uf="RS",
    modalidades=None,
    paginas_por_modalidade=2,
    max_contratacoes_detalhadas=PNCP_MAX_CONTRATACOES_DETALHADAS,
    timeout_consulta=8,
    timeout_detalhe=15,
    tentativas_consulta=3,
    usar_valor_total_contratacao=False,
    ampliar_candidatos=False,
    excluir_municipio="Joia",
):
    modalidades = modalidades or PNCP_MODALIDADES_PADRAO
    termos = _termos_pncp(descricao_busca)
    termos_candidatos = _termos_candidatos_pncp(termos, ampliar=ampliar_candidatos)
    busca_norm = normalizar(descricao_busca)
    fontes = []
    erros = []
    consultas_ok = 0
    contratacoes_detalhadas = 0
    periodos = []
    fim_periodo = date.today()
    dias_restantes = max(1, int(dias))
    while dias_restantes > 0:
        tamanho_periodo = min(7, dias_restantes)
        inicio_periodo = fim_periodo - timedelta(days=tamanho_periodo)
        periodos.append((inicio_periodo, fim_periodo))
        fim_periodo = inicio_periodo - timedelta(days=1)
        dias_restantes -= tamanho_periodo

    for inicio_periodo, fim_periodo in periodos:
        for modalidade in modalidades:
            for pagina in range(1, paginas_por_modalidade + 1):
                params = {
                    "dataInicial": inicio_periodo.strftime("%Y%m%d"),
                    "dataFinal": fim_periodo.strftime("%Y%m%d"),
                    "codigoModalidadeContratacao": modalidade,
                    "pagina": pagina,
                }
                if uf:
                    params["uf"] = uf

                url = f"{PNCP_BASE_URL}/v1/contratacoes/publicacao?{urllib.parse.urlencode(params)}"
                try:
                    dados = _abrir_json(
                        url,
                        timeout=timeout_consulta,
                        tentativas=tentativas_consulta,
                    )
                except Exception as erro:
                    erros.append(f"{inicio_periodo:%d/%m/%Y}-{fim_periodo:%d/%m/%Y}, modalidade {modalidade}, pagina {pagina}: {erro}")
                    continue
                consultas_ok += 1
                registros = dados.get("data", []) if isinstance(dados, dict) else []
                if not registros:
                    break

                for registro in registros:
                    if _registro_do_municipio(registro, excluir_municipio):
                        continue

                    _, score_contratacao, tem_termo_contratacao = _registro_pncp_candidato(
                        registro,
                        busca_norm,
                        termos_candidatos,
                    )
                    if (
                        not tem_termo_contratacao
                        and score_contratacao < PNCP_MIN_SCORE_CONTRATACAO_DETALHE
                    ):
                        continue

                    unidade = registro.get("unidadeOrgao") or {}
                    orgao = registro.get("orgaoEntidade") or {}

                    if contratacoes_detalhadas >= max_contratacoes_detalhadas:
                        if not usar_valor_total_contratacao:
                            continue
                        fonte_fallback = _fonte_contratacao_pncp(registro, descricao_busca, score_contratacao)
                        if fonte_fallback:
                            fontes.append(fonte_fallback)
                            if len(fontes) >= limite:
                                return fontes
                        continue

                    try:
                        itens = _listar_itens_pncp(registro, timeout=timeout_detalhe)
                        contratacoes_detalhadas += 1
                    except Exception as erro:
                        erros.append(
                            f"Itens PNCP {registro.get('anoCompra', '')}/"
                            f"{registro.get('sequencialCompra', '')}: {erro}"
                        )
                        itens = []

                    encontrou_item_valido = False

                    for item in itens:
                        descricao_item = item.get("descricao", "") or registro.get("objetoCompra", "")
                        compativel, score, termos_encontrados = _item_pncp_compativel(
                            descricao_item,
                            busca_norm,
                            termos,
                        )
                        if not compativel:
                            continue

                        resultados = []
                        if item.get("temResultado"):
                            try:
                                resultados = _listar_resultados_item_pncp(
                                    registro,
                                    item.get("numeroItem"),
                                    timeout=timeout_detalhe,
                                )
                            except Exception:
                                resultados = []

                        if resultados:
                            for resultado in resultados:
                                valor_unitario = converter_numero(resultado.get("valorUnitarioHomologado"))
                                if not valor_unitario:
                                    continue
                                fontes.append(
                                    FontePreco(
                                        origem="PNCP",
                                        descricao=descricao_item,
                                        valor_unitario=valor_unitario,
                                        valor_total=converter_numero(resultado.get("valorTotalHomologado")),
                                        quantidade=converter_numero(resultado.get("quantidadeHomologada")),
                                        unidade=item.get("unidadeMedida", ""),
                                        data_referencia=_data_pncp(resultado.get("dataResultado") or item.get("dataAtualizacao")),
                                        fornecedor_nome=resultado.get("nomeRazaoSocialFornecedor", ""),
                                        fornecedor_cnpj=resultado.get("niFornecedor", ""),
                                        orgao=orgao.get("razaoSocial", ""),
                                        municipio=unidade.get("municipioNome", ""),
                                        uf=unidade.get("ufSigla", ""),
                                        link=_link_pncp(registro),
                                        evidencia=(
                                            f"PNCP compra {registro.get('anoCompra', '')}/"
                                            f"{registro.get('sequencialCompra', '')}, item {item.get('numeroItem', '')}, "
                                            f"resultado {resultado.get('sequencialResultado', '')}; "
                                            f"termos encontrados: {', '.join(termos_encontrados) or '-'}"
                                        ),
                                        score=round(max(score, score_contratacao), 2),
                                        status_validacao="revisao obrigatoria",
                                        motivos_alerta="Resultado PNCP importado automaticamente; conferir compatibilidade do item antes de anexar ao processo.",
                                    )
                                )
                                encontrou_item_valido = True
                                if len(fontes) >= limite:
                                    return fontes
                        else:
                            valor_unitario = converter_numero(item.get("valorUnitarioEstimado"))
                            if not valor_unitario:
                                continue
                            fontes.append(
                                FontePreco(
                                    origem="PNCP",
                                    descricao=descricao_item,
                                    valor_unitario=valor_unitario,
                                    valor_total=converter_numero(item.get("valorTotal")),
                                    quantidade=converter_numero(item.get("quantidade")),
                                    unidade=item.get("unidadeMedida", ""),
                                    data_referencia=_data_pncp(item.get("dataAtualizacao") or registro.get("dataPublicacaoPncp")),
                                    fornecedor_nome="",
                                    fornecedor_cnpj="",
                                    orgao=orgao.get("razaoSocial", ""),
                                    municipio=unidade.get("municipioNome", ""),
                                    uf=unidade.get("ufSigla", ""),
                                    link=_link_pncp(registro),
                                    evidencia=(
                                        f"PNCP compra {registro.get('anoCompra', '')}/"
                                        f"{registro.get('sequencialCompra', '')}, item {item.get('numeroItem', '')}; "
                                        f"termos encontrados: {', '.join(termos_encontrados) or '-'}"
                                    ),
                                    score=round(max(score, score_contratacao), 2),
                                    status_validacao="revisao obrigatoria",
                                    motivos_alerta="Preco estimado do PNCP sem resultado homologado; usar somente apos conferencia.",
                                )
                            )
                            encontrou_item_valido = True
                            if len(fontes) >= limite:
                                return fontes

                    if (
                        usar_valor_total_contratacao
                        and not encontrou_item_valido
                        and score_contratacao >= 70
                    ):
                        fonte_fallback = _fonte_contratacao_pncp(registro, descricao_busca, score_contratacao)
                        if fonte_fallback:
                            fontes.append(fonte_fallback)
                            if len(fontes) >= limite:
                                return fontes

    if not fontes and erros and consultas_ok == 0:
        raise RuntimeError("Nao foi possivel consultar o PNCP. " + " | ".join(erros[:3]))

    return fontes


def _buscar_serpapi(query, limite):
    chave = os.getenv("SERPAPI_KEY")
    if not chave:
        return [], "SERPAPI_KEY nao configurada."

    params = {
        "engine": "google",
        "q": query,
        "api_key": chave,
        "num": min(limite, 10),
        "hl": "pt-br",
        "gl": "br",
    }
    dados = _abrir_json(f"https://serpapi.com/search.json?{urllib.parse.urlencode(params)}")
    return dados.get("organic_results", []), ""


def _buscar_bing(query, limite):
    chave = os.getenv("BING_SEARCH_KEY")
    if not chave:
        return [], "BING_SEARCH_KEY nao configurada."

    params = {"q": query, "count": min(limite, 10), "mkt": "pt-BR"}
    req = urllib.request.Request(
        f"https://api.bing.microsoft.com/v7.0/search?{urllib.parse.urlencode(params)}",
        headers={"Ocp-Apim-Subscription-Key": chave},
    )
    with urllib.request.urlopen(req, timeout=20) as resposta:
        dados = json.loads(resposta.read().decode("utf-8"))
    return dados.get("webPages", {}).get("value", []), ""


MARKETPLACE_DOMINIOS = (
    "mercadolivre.com",
    "amazon.",
    "shopee.",
    "magazineluiza.com",
    "americanas.com",
    "casasbahia.com",
    "pontofrio.com",
    "extra.com.br",
    "aliexpress.",
    "olx.com",
    "enjoei.com",
)

COMPARADOR_DOMINIOS = (
    "buscape.com",
    "zoom.com.br",
    "jacotei.com.br",
    "bondfaro.com.br",
)

INDICIOS_LISTAGEM_WEB = (
    "lista",
    "busca",
    "search",
    "catalogo",
    "categoria",
    "category",
    "collection",
    "collections",
    "tag",
)

INDICIOS_PRODUTO_WEB = (
    "produto",
    "product",
    "produtos/",
    "p/",
    "sku",
)

TERMOS_PRECO_PROMOCIONAL = (
    "pix",
    "cupom",
    "desconto",
    "promocao",
    "promoção",
    "oferta",
    "a vista",
    "à vista",
)


def _dominio_url(link):
    try:
        return urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
    except ValueError:
        return ""


def _caminho_url(link):
    try:
        parsed = urllib.parse.urlparse(link)
        return f"{parsed.path.lower()} {parsed.query.lower()}"
    except ValueError:
        return ""


def _dominio_contem(dominio, candidatos):
    return any(candidato in dominio for candidato in candidatos)


def _parece_pagina_listagem(link, titulo, snippet):
    caminho = _caminho_url(link)
    texto = normalizar(f"{titulo} {snippet}")
    tem_indicio_listagem = any(indicio in caminho for indicio in INDICIOS_LISTAGEM_WEB)
    tem_indicio_produto = any(indicio in caminho for indicio in INDICIOS_PRODUTO_WEB)
    texto_listagem = any(
        termo in texto
        for termo in (
            "resultados",
            "varios produtos",
            "vários produtos",
            "categoria",
            "catalogo",
            "catálogo",
            "lista de",
            "encontre",
        )
    )
    return (tem_indicio_listagem and not tem_indicio_produto) or texto_listagem


def _classificar_resultado_web(link, titulo, snippet):
    dominio = _dominio_url(link)
    texto = normalizar(f"{titulo} {snippet} {link}")
    motivos = []
    status = "revisao obrigatoria"
    penalidade = 0
    tipo = "loja/fornecedor"

    if _dominio_contem(dominio, MARKETPLACE_DOMINIOS):
        tipo = "marketplace"
        status = "uso excepcional"
        penalidade += 55
        motivos.append("Marketplace; usar somente em ultimo caso e justificar a ausencia de fonte melhor.")
    elif _dominio_contem(dominio, COMPARADOR_DOMINIOS):
        tipo = "comparador"
        status = "uso excepcional"
        penalidade += 45
        motivos.append("Comparador de precos; use apenas para localizar a loja final, nao como evidencia principal.")

    if _parece_pagina_listagem(link, titulo, snippet):
        status = "nao usar sem pagina do produto"
        penalidade += 35
        motivos.append("Link parece pagina de busca/categoria/listagem; abra o produto exato antes de aprovar.")

    if any(termo in texto for termo in TERMOS_PRECO_PROMOCIONAL):
        motivos.append("Pode haver preco promocional, Pix, cupom ou desconto; usar o preco original sem desconto quando existir.")

    motivos.append("Capturar print/PDF da pagina do produto com data e hora da consulta.")
    motivos.append("Conferir produto exato, marca/modelo, frete, disponibilidade e CNPJ/identificacao do fornecedor.")
    return tipo, status, penalidade, " ".join(motivos)


def buscar_web(descricao_busca, limite=10):
    resultados = []
    aviso = ""
    query = f'{descricao_busca} preco comprar "R$" -mercadolivre -amazon -shopee'

    if os.getenv("SERPAPI_KEY"):
        resultados, aviso = _buscar_serpapi(query, limite)
    elif os.getenv("BING_SEARCH_KEY"):
        resultados, aviso = _buscar_bing(query, limite)
    else:
        acesso = agora_iso()
        links_busca = [
            ("Google", f"https://www.google.com/search?{urllib.parse.urlencode({'q': query})}"),
            ("Bing", f"https://www.bing.com/search?{urllib.parse.urlencode({'q': query})}"),
        ]
        fontes_manuais = [
            FontePreco(
                origem="Internet",
                descricao=f"Busca manual na internet - {nome}",
                valor_unitario=None,
                valor_total=None,
                data_referencia=acesso,
                link=link,
                evidencia=f"Link de busca gerado em {acesso}; exige conferencia manual e registro do preco encontrado.",
                score=0,
                status_validacao="revisao obrigatoria",
                motivos_alerta=(
                    "Pesquisa web automatica sem chave de API. Abra um resultado em loja/fornecedor, confirme o produto exato, "
                    "use o preco original sem desconto Pix/cupom, inclua frete quando aplicavel e capture print/PDF com data e hora."
                ),
            )
            for nome, link in links_busca[:limite]
        ]
        return fontes_manuais, "Configure SERPAPI_KEY ou BING_SEARCH_KEY para extrair resultados e precos automaticamente. Foram gerados links para conferencia manual."

    fontes = []
    acesso = agora_iso()
    busca_norm = normalizar(descricao_busca)

    for item in resultados[:limite]:
        titulo = item.get("title") or item.get("name") or ""
        link = item.get("link") or item.get("url") or ""
        snippet = item.get("snippet") or item.get("description") or ""
        texto = f"{titulo} {snippet}"
        valor = _texto_preco_para_float(texto)
        tipo, status_validacao, penalidade, motivos_alerta = _classificar_resultado_web(link, titulo, snippet)
        score = max(0, fuzz.token_set_ratio(busca_norm, normalizar(texto)) - penalidade)

        fontes.append(
            FontePreco(
                origem="Internet",
                descricao=titulo or descricao_busca,
                valor_unitario=valor,
                valor_total=valor,
                data_referencia=acesso,
                link=link,
                evidencia=f"Acesso em {acesso}. Tipo: {tipo}. Trecho: {snippet[:300]}",
                score=round(score, 2),
                status_validacao=status_validacao,
                motivos_alerta=motivos_alerta,
            )
        )

    fontes.sort(key=lambda fonte: (fonte.status_validacao == "uso excepcional", fonte.status_validacao.startswith("nao usar"), -fonte.score))
    if fontes and all(fonte.status_validacao != "revisao obrigatoria" for fonte in fontes):
        aviso = (aviso + " " if aviso else "") + "Internet retornou apenas marketplace/comparador/listagem; use somente como excecao justificada."
    return fontes[:limite], aviso


def buscar_fornecedores(descricao_busca):
    fontes = []
    for cotacao in listar_cotacoes_por_descricao(descricao_busca):
        valor_unitario = converter_numero(cotacao.get("valor_unitario"))
        valor_total = converter_numero(cotacao.get("valor_total"))
        fontes.append(
            FontePreco(
                origem="Fornecedor",
                descricao=cotacao.get("item_pesquisado", ""),
                valor_unitario=valor_unitario,
                valor_total=valor_total,
                quantidade=converter_numero(cotacao.get("quantidade")),
                unidade=cotacao.get("unidade", ""),
                data_referencia=cotacao.get("data_resposta") or cotacao.get("data_solicitacao") or cotacao.get("criado_em", ""),
                fornecedor_nome=cotacao.get("fornecedor_nome", ""),
                fornecedor_cnpj=cotacao.get("cpf_cnpj", ""),
                municipio=cotacao.get("municipio", ""),
                uf=cotacao.get("uf", ""),
                evidencia=cotacao.get("evidencia", ""),
                score=80,
                status_validacao="pendente",
                motivos_alerta="Cotacao direta deve conter solicitacao formal, resposta do fornecedor e justificativa da escolha.",
            )
        )
    return fontes
