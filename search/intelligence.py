import logging
import re
from datetime import datetime

from utils.util import converter_numero, normalizar, termos_compativeis


logger = logging.getLogger("pesquisa.inteligencia")


TERMOS_GENERICOS_CATEGORIA = {
    "aquisicao", "contratacao", "fornecimento", "material", "materiais",
    "produto", "produtos", "item", "itens", "servico", "servicos",
}

CATEGORIAS = {
    "avental": {
        "termos": {"avental", "aventaes"},
        "contexto": {"impermeavel", "pvc", "vinil", "plastico", "proteçao", "protecao"},
        "divergentes": {
            "fita", "cano", "tubo", "caps", "cap", "luva", "conexao", "joelho",
            "registro", "solda", "cola", "adesivo", "mangueira",
        },
    },
    "fita": {"termos": {"fita"}, "contexto": {"adesiva", "isolante", "pvc"}, "divergentes": set()},
    "cano": {"termos": {"cano", "tubo"}, "contexto": {"pvc", "hidraulico"}, "divergentes": set()},
    "luva": {"termos": {"luva", "luvas"}, "contexto": {"protecao", "procedimento", "pvc"}, "divergentes": set()},
    "rele": {"termos": {"rele", "relé"}, "contexto": {"fase", "falta", "temporizador", "fotoeletrico"}, "divergentes": set()},
    "sensor": {"termos": {"sensor", "sensores"}, "contexto": {"presenca", "nivel", "proximidade"}, "divergentes": set()},
    "cadeira": {"termos": {"cadeira", "poltrona"}, "contexto": {"escritorio", "giratoria"}, "divergentes": set()},
    "mesa": {"termos": {"mesa", "bancada"}, "contexto": {"escritorio", "reuniao"}, "divergentes": set()},
    "notebook": {"termos": {"notebook", "laptop"}, "contexto": {"processador", "memoria", "ssd"}, "divergentes": set()},
    "computador": {"termos": {"computador", "desktop", "microcomputador"}, "contexto": {"processador", "memoria", "ssd"}, "divergentes": set()},
    "impressora": {"termos": {"impressora", "multifuncional"}, "contexto": {"laser", "jato", "toner"}, "divergentes": set()},
    "pneu": {"termos": {"pneu", "pneus"}, "contexto": {"radial", "aro"}, "divergentes": set()},
}

FONTES_PRIORIDADE = {
    "pncp": 100,
    "compras.gov": 95,
    "comprasgov": 95,
    "licitacon": 90,
    "tce": 90,
    "portal oficial": 70,
    "fornecedor": 35,
    "internet": 45,
}


def _tokens(texto):
    return set(normalizar(texto).split())


def detectar_categoria(texto):
    texto_norm = normalizar(texto)
    palavras = _tokens(texto_norm)
    for categoria, regra in CATEGORIAS.items():
        if palavras.intersection({normalizar(t) for t in regra["termos"]}):
            return categoria
    for palavra in palavras:
        if palavra not in TERMOS_GENERICOS_CATEGORIA and len(palavra) >= 4:
            return palavra
    return ""


def extrair_medidas(texto):
    bruto = str(texto or "").replace(",", ".")
    medidas = []
    for achado in re.findall(r"\b\d+(?:\.\d+)?\b", bruto):
        valor = converter_numero(achado)
        if valor is None:
            continue
        if 0 < valor < 10 and "." in achado:
            valor = valor * 100
        medidas.append(str(int(valor)) if float(valor).is_integer() else str(valor))
    return list(dict.fromkeys(medidas))


def extrair_unidade(texto):
    texto_norm = normalizar(texto)
    for unidade in ["un", "und", "unidade", "unidades", "kg", "g", "m", "cm", "mm", "l", "ml", "par", "caixa"]:
        if re.search(rf"\b{re.escape(unidade)}\b", texto_norm):
            return unidade
    return ""


def enriquecer_criterios_contextuais(descricao, criterios):
    criterios = dict(criterios or {})
    texto_norm = normalizar(descricao)
    categoria = criterios.get("categoria") or detectar_categoria(descricao)
    materiais = []
    for material in ["pvc", "vinil", "aco", "inox", "aluminio", "plastico", "madeira", "latex", "nitrilico"]:
        if termos_compativeis(material, texto_norm):
            materiais.append(material)
    termos_proibidos = list(criterios.get("termos_proibidos") or criterios.get("termos_excluir") or [])
    if categoria in CATEGORIAS:
        termos_proibidos.extend(sorted(CATEGORIAS[categoria].get("divergentes") or []))
    criterios.update({
        "categoria": categoria,
        "nucleo_tecnico": criterios.get("nucleo_tecnico") or categoria,
        "materiais": list(dict.fromkeys(criterios.get("materiais", []) + materiais)),
        "medidas": list(dict.fromkeys(criterios.get("medidas", []) + extrair_medidas(descricao))),
        "unidade": criterios.get("unidade") or extrair_unidade(descricao),
        "termos_proibidos": list(dict.fromkeys([normalizar(t) for t in termos_proibidos if normalizar(t)])),
    })
    return criterios


def semantic_category_match(descricao_busca, descricao_resultado, criterios=None):
    criterios = criterios or {}
    categoria_busca = criterios.get("categoria") or detectar_categoria(descricao_busca)
    categoria_resultado = detectar_categoria(descricao_resultado)
    resultado_norm = normalizar(descricao_resultado)
    termos_proibidos = criterios.get("termos_proibidos") or criterios.get("termos_excluir") or []
    proibidos_encontrados = [termo for termo in termos_proibidos if termos_compativeis(termo, resultado_norm)]

    if categoria_busca and categoria_busca in CATEGORIAS:
        regra = CATEGORIAS[categoria_busca]
        categoria_no_resultado = any(
            termos_compativeis(termo, resultado_norm)
            for termo in regra.get("termos", set())
        )
        divergentes = [
            termo for termo in regra.get("divergentes", set())
            if termos_compativeis(termo, resultado_norm)
        ]
        if divergentes and not categoria_no_resultado:
            logger.debug(
                "[critical_divergence] categoria_detectada=%s categoria_divergente=%s candidato_descartado=%r",
                categoria_busca,
                ",".join(divergentes),
                descricao_resultado,
            )
            return {
                "ok": False,
                "score": 0,
                "categoria_detectada": categoria_busca,
                "categoria_resultado": categoria_resultado,
                "motivo": f"categoria_divergente:{','.join(divergentes)}",
                "compatibility_reasons": [],
                "rejection_reasons": [f"categoria divergente: {', '.join(divergentes)}"],
            }
        if not categoria_no_resultado:
            logger.debug(
                "[categoria_divergente] categoria_detectada=%s categoria_resultado=%s candidato_descartado=%r",
                categoria_busca,
                categoria_resultado,
                descricao_resultado,
            )
            return {
                "ok": False,
                "score": 0,
                "categoria_detectada": categoria_busca,
                "categoria_resultado": categoria_resultado,
                "motivo": "categoria_principal_incompativel",
                "compatibility_reasons": [],
                "rejection_reasons": ["categoria principal incompatível"],
            }

    if proibidos_encontrados:
        return {
            "ok": False,
            "score": 0,
            "categoria_detectada": categoria_busca,
            "categoria_resultado": categoria_resultado,
            "motivo": f"termos_proibidos:{','.join(proibidos_encontrados)}",
            "compatibility_reasons": [],
            "rejection_reasons": [f"termos proibidos encontrados: {', '.join(proibidos_encontrados)}"],
        }

    if categoria_busca and categoria_resultado and categoria_busca == categoria_resultado:
        score = 100
    elif categoria_busca and not categoria_resultado:
        score = 65
    else:
        score = 80
    return {
        "ok": True,
        "score": score,
        "categoria_detectada": categoria_busca,
        "categoria_resultado": categoria_resultado,
        "motivo": "",
        "compatibility_reasons": [
            motivo for motivo in [
                "categoria compatível" if categoria_busca and categoria_resultado == categoria_busca else "",
                "contexto sem divergência crítica",
            ] if motivo
        ],
        "rejection_reasons": [],
    }


def quantidade_desejada(qtd_min=None, qtd_max=None, criterios=None):
    criterios = criterios or {}
    for chave in ["quantidade_desejada", "quantidade"]:
        valor = converter_numero(criterios.get(chave))
        if valor:
            return valor
    minimo = converter_numero(qtd_min)
    maximo = converter_numero(qtd_max)
    if minimo and maximo and minimo == maximo:
        return maximo
    if maximo and maximo < 999999:
        return maximo
    return minimo or maximo


def quantity_similarity_score(quantidade_resultado, quantidade_alvo):
    qtd = converter_numero(quantidade_resultado)
    alvo = converter_numero(quantidade_alvo)
    if not qtd or qtd <= 0 or not alvo or alvo <= 0:
        return 50
    proporcao = qtd / alvo
    if qtd <= 50:
        base = 20
    elif qtd <= 200:
        base = 45
    elif qtd <= 500:
        base = 70
    else:
        base = 88
    ajuste = max(0, 100 - abs(1 - proporcao) * 55)
    return round(min(100, base * 0.55 + ajuste * 0.45), 2)


def source_priority_score(fonte):
    fonte_norm = normalizar(fonte)
    for chave, score in FONTES_PRIORIDADE.items():
        if chave in fonte_norm:
            return score
    if fonte_norm.startswith("http"):
        return 45
    return 55


def recency_score(data_texto, ano=None):
    ano_num = converter_numero(ano)
    datas = []
    texto = str(data_texto or "")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            datas.append(datetime.strptime(texto[:19], fmt))
            break
        except ValueError:
            pass
    if not datas and ano_num:
        try:
            datas.append(datetime(int(ano_num), 1, 1))
        except ValueError:
            pass
    if not datas:
        return 55
    dias = max(0, (datetime.now() - datas[0]).days)
    if dias <= 180:
        return 100
    if dias <= 365:
        return 85
    if dias <= 730:
        return 65
    if dias <= 1095:
        return 45
    return 25


def calcular_score_final_inteligente(
    *,
    score_textual,
    score_categoria,
    score_quantidade,
    score_tecnico=100,
    score_recencia=55,
    score_fonte=55,
):
    score = (
        float(score_textual or 0) * 0.30
        + float(score_categoria or 0) * 0.25
        + float(score_quantidade or 0) * 0.15
        + float(score_tecnico or 0) * 0.15
        + float(score_recencia or 0) * 0.10
        + float(score_fonte or 0) * 0.05
    )
    return round(max(0, min(100, score)), 2)
