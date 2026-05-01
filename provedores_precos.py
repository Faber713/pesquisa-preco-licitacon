import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from rapidfuzz import fuzz

from app_storage import listar_cotacoes_por_descricao
from fontes_preco import FontePreco, agora_iso
from util import converter_numero, normalizar, palavras_fortes


PNCP_BASE_URL = "https://pncp.gov.br/api/consulta"
PNCP_DADOS_URL = "https://pncp.gov.br/api/pncp"
PNCP_MODALIDADES_PADRAO = [8, 6, 7, 9, 5]


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


def _abrir_json(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 pesquisa-preco-licitacon/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


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


def _listar_itens_pncp(registro):
    orgao = registro.get("orgaoEntidade") or {}
    cnpj = orgao.get("cnpj")
    ano = registro.get("anoCompra")
    sequencial = registro.get("sequencialCompra")
    if not cnpj or not ano or not sequencial:
        return []

    url = f"{PNCP_DADOS_URL}/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
    dados = _abrir_json(url, timeout=15)
    return dados if isinstance(dados, list) else []


def _listar_resultados_item_pncp(registro, numero_item):
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
    dados = _abrir_json(url, timeout=15)
    return dados if isinstance(dados, list) else []


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
):
    modalidades = modalidades or PNCP_MODALIDADES_PADRAO
    termos = palavras_fortes(descricao_busca)
    busca_norm = normalizar(descricao_busca)
    fontes = []
    erros = []
    consultas_ok = 0
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
                    "tamanhoPagina": 10,
                }
                if uf:
                    params["uf"] = uf

                url = f"{PNCP_BASE_URL}/v1/contratacoes/publicacao?{urllib.parse.urlencode(params)}"
                try:
                    dados = _abrir_json(url, timeout=8)
                except Exception as erro:
                    erros.append(f"{inicio_periodo:%d/%m/%Y}-{fim_periodo:%d/%m/%Y}, modalidade {modalidade}, pagina {pagina}: {erro}")
                    continue
                consultas_ok += 1
                registros = dados.get("data", []) if isinstance(dados, dict) else []
                if not registros:
                    break

                for registro in registros:
                    objeto = str(registro.get("objetoCompra", ""))
                    unidade = registro.get("unidadeOrgao") or {}
                    orgao = registro.get("orgaoEntidade") or {}
                    texto_contratacao = " ".join([
                        objeto,
                        str(unidade.get("nomeUnidade", "")),
                        str(orgao.get("razaoSocial", "")),
                        str(registro.get("modalidadeNome", "")),
                    ])
                    score_contratacao = fuzz.token_set_ratio(busca_norm, normalizar(texto_contratacao))

                    try:
                        itens = _listar_itens_pncp(registro)
                    except Exception:
                        itens = []

                    for item in itens:
                        descricao_item = item.get("descricao", "") or objeto
                        texto_descricao_item = normalizar(descricao_item)
                        score = fuzz.token_set_ratio(busca_norm, texto_descricao_item)
                        tokens_item = set(re.findall(r"\w+", texto_descricao_item))
                        tem_termo_item = any(termo in tokens_item for termo in termos)
                        if not tem_termo_item and score < 60:
                            continue

                        resultados = []
                        if item.get("temResultado"):
                            try:
                                resultados = _listar_resultados_item_pncp(registro, item.get("numeroItem"))
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
                                            f"resultado {resultado.get('sequencialResultado', '')}"
                                        ),
                                        score=round(max(score, score_contratacao), 2),
                                        status_validacao="revisao obrigatoria",
                                        motivos_alerta="Resultado PNCP importado automaticamente; conferir compatibilidade do item antes de anexar ao processo.",
                                    )
                                )
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
                                        f"{registro.get('sequencialCompra', '')}, item {item.get('numeroItem', '')}"
                                    ),
                                    score=round(max(score, score_contratacao), 2),
                                    status_validacao="revisao obrigatoria",
                                    motivos_alerta="Preco estimado do PNCP sem resultado homologado; usar somente apos conferencia.",
                                )
                            )
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


def buscar_web(descricao_busca, limite=10):
    resultados = []
    aviso = ""
    query = f'{descricao_busca} preço comprar "R$"'

    if os.getenv("SERPAPI_KEY"):
        resultados, aviso = _buscar_serpapi(query, limite)
    elif os.getenv("BING_SEARCH_KEY"):
        resultados, aviso = _buscar_bing(query, limite)
    else:
        acesso = agora_iso()
        links_busca = [
            ("Google", f"https://www.google.com/search?{urllib.parse.urlencode({'q': query})}"),
            ("Bing", f"https://www.bing.com/search?{urllib.parse.urlencode({'q': query})}"),
            ("Mercado Livre", f"https://lista.mercadolivre.com.br/{urllib.parse.quote_plus(descricao_busca)}"),
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
                motivos_alerta="Pesquisa web automatica sem chave de API. Abra o link, confirme preco, fornecedor, frete e data de acesso.",
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
        score = fuzz.token_set_ratio(busca_norm, normalizar(texto))

        fontes.append(
            FontePreco(
                origem="Internet",
                descricao=titulo or descricao_busca,
                valor_unitario=valor,
                valor_total=valor,
                data_referencia=acesso,
                link=link,
                evidencia=f"Acesso em {acesso}. Trecho: {snippet[:300]}",
                score=round(score, 2),
                status_validacao="revisao obrigatoria",
                motivos_alerta="Preco de internet extraido automaticamente; conferir pagina, frete, marca/modelo e data/hora de acesso.",
            )
        )

    return fontes, aviso


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
