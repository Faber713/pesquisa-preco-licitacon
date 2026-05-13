import hashlib
import statistics

from flask import session

from utils.util import converter_numero
from web.services.filtros_service import gerar_item_uid


SESSION_KEY = "cesta_precos"
METODOLOGIA_KEY = "metodologia_formacao_preco"
TOTAL_ITENS_KEY = "cesta_total_itens"


def _preco(valor):
    numero = converter_numero(valor)
    return float(numero) if numero is not None else None


def _resultado_id(dados):
    base = "|".join(
        str(dados.get(chave, ""))
        for chave in ["item_uid", "descricao", "orgao", "fornecedor", "valor_unitario", "processo", "ano", "fonte"]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _metodologia_padrao():
    return session.get(METODOLOGIA_KEY, "mediana")


def _nova_cesta():
    return {}


def _normalizar_cesta(valor):
    if isinstance(valor, dict):
        for uid, grupo in valor.items():
            grupo.setdefault("item_uid", uid)
            grupo.setdefault("status", "em_edicao")
            grupo.setdefault("resultados", [])
        return valor

    cesta = _nova_cesta()
    if isinstance(valor, list):
        for antigo in valor:
            item_uid = antigo.get("item_uid") or gerar_item_uid(
                antigo.get("item_pesquisado") or antigo.get("descricao", ""),
                antigo.get("quantidade", ""),
            )
            descricao_item = antigo.get("item_pesquisado") or antigo.get("descricao") or "Item sem descricao"
            cesta.setdefault(
                item_uid,
                {
                    "item_uid": item_uid,
                    "numero": antigo.get("item_numero", ""),
                    "descricao": descricao_item,
                    "quantidade": antigo.get("quantidade", ""),
                    "resultados_alvo": antigo.get("resultados_alvo", ""),
                    "metodologia": antigo.get("metodologia_formacao_preco") or _metodologia_padrao(),
                    "status": "em_edicao",
                    "resultados": [],
                },
            )
            antigo["id"] = antigo.get("id") or _resultado_id({**antigo, "item_uid": item_uid})
            cesta[item_uid]["resultados"].append(antigo)
    return cesta


def obter_cesta():
    cesta = _normalizar_cesta(session.get(SESSION_KEY, _nova_cesta()))
    session[SESSION_KEY] = cesta
    return cesta


def salvar_cesta(cesta):
    session[SESSION_KEY] = cesta
    session.modified = True


def limpar_cesta():
    salvar_cesta(_nova_cesta())


def _todos_resultados(cesta=None):
    cesta = obter_cesta() if cesta is None else cesta
    return [
        resultado
        for grupo in cesta.values()
        for resultado in grupo.get("resultados", [])
    ]


def _ordenar_grupos(cesta):
    def chave(item):
        _, grupo = item
        try:
            return int(grupo.get("numero") or 999999)
        except (TypeError, ValueError):
            return 999999

    return sorted(cesta.items(), key=chave)


def _definir_total_itens(valor):
    try:
        total = int(valor)
    except (TypeError, ValueError):
        return
    if total > 0:
        session[TOTAL_ITENS_KEY] = max(total, int(session.get(TOTAL_ITENS_KEY, 0) or 0))
        session.modified = True


def _ativar_item(cesta, item_uid):
    for uid, grupo in cesta.items():
        if uid == item_uid:
            grupo["status"] = "em_edicao"
        elif grupo.get("status") == "em_edicao":
            grupo["status"] = "finalizado"


def _proximo_item_uid(cesta, item_uid):
    grupos = _ordenar_grupos(cesta)
    uids = [uid for uid, _ in grupos]
    if item_uid not in uids:
        return None
    inicio = uids.index(item_uid) + 1
    for uid in uids[inicio:]:
        if cesta[uid].get("status") != "finalizado":
            return uid
    for uid in uids:
        if cesta[uid].get("status") != "finalizado":
            return uid
    return None


def adicionar_preco(dados):
    cesta = obter_cesta()
    item_pesquisado = dados.get("item_pesquisado", "").strip() or dados.get("descricao", "").strip()
    quantidade_item = dados.get("quantidade_item", "").strip() or dados.get("quantidade", "").strip()
    numero_item = dados.get("item_numero", "").strip()
    resultados_alvo = dados.get("resultados_alvo", "").strip()
    _definir_total_itens(dados.get("total_itens_cesta"))
    item_uid = dados.get("item_uid", "").strip() or gerar_item_uid(item_pesquisado, quantidade_item)
    resultado_uid = dados.get("resultado_uid", "").strip()

    item = {
        "id": resultado_uid or dados.get("id") or _resultado_id({**dados, "item_uid": item_uid}),
        "item_uid": item_uid,
        "item_pesquisado": item_pesquisado,
        "descricao": dados.get("descricao", "").strip(),
        "orgao": dados.get("orgao", "").strip(),
        "fornecedor": dados.get("fornecedor", "").strip(),
        "valor_unitario": dados.get("valor_unitario", "").strip(),
        "quantidade": dados.get("quantidade", "").strip(),
        "score": dados.get("score", "").strip(),
        "fonte": dados.get("fonte", "LicitaCon RS").strip() or "LicitaCon RS",
        "link_origem": (
            dados.get("link_origem", "")
            or dados.get("link_licitacon", "")
            or dados.get("link", "")
        ).strip(),
        "modalidade": dados.get("modalidade", "").strip(),
        "ano": dados.get("ano", "").strip(),
        "processo": dados.get("processo", "").strip(),
        "considerar": dados.get("considerar", "1") != "0",
        "justificativa": dados.get("justificativa", "").strip(),
    }

    if not item["descricao"] or _preco(item["valor_unitario"]) is None:
        return False

    grupo = cesta.setdefault(
        item_uid,
        {
            "item_uid": item_uid,
            "numero": numero_item,
            "descricao": item_pesquisado,
            "quantidade": quantidade_item,
            "resultados_alvo": resultados_alvo,
            "metodologia": _metodologia_padrao(),
            "status": "em_edicao",
            "resultados": [],
        },
    )
    if numero_item and not grupo.get("numero"):
        grupo["numero"] = numero_item
    if resultados_alvo:
        grupo["resultados_alvo"] = resultados_alvo
    if grupo.get("status") == "finalizado":
        salvar_cesta(cesta)
        return False
    if grupo.get("status") != "finalizado":
        _ativar_item(cesta, item_uid)

    if not any(existente.get("id") == item["id"] for existente in grupo["resultados"]):
        grupo["resultados"].append(item)
        salvar_cesta(cesta)
    else:
        salvar_cesta(cesta)
    return True


def remover_preco(item_id, item_uid=""):
    cesta = obter_cesta()
    uids = [item_uid] if item_uid and item_uid in cesta else list(cesta.keys())
    for uid in uids:
        grupo = cesta.get(uid)
        if not grupo:
            continue
        grupo["resultados"] = [
            item for item in grupo.get("resultados", []) if item.get("id") != item_id
        ]
        if not grupo["resultados"]:
            cesta.pop(uid, None)
    salvar_cesta(cesta)


def remover_item(item_uid):
    cesta = obter_cesta()
    cesta.pop(item_uid, None)
    if cesta and not any(grupo.get("status") == "em_edicao" for grupo in cesta.values()):
        primeiro_uid = _ordenar_grupos(cesta)[0][0]
        cesta[primeiro_uid]["status"] = "em_edicao"
    salvar_cesta(cesta)


def remover_preco_por_dados(dados):
    remover_preco(
        dados.get("resultado_uid") or dados.get("id") or _resultado_id(dados),
        dados.get("item_uid", ""),
    )


def definir_consideracao(item_id, considerar, justificativa="", item_uid=""):
    cesta = obter_cesta()
    uids = [item_uid] if item_uid and item_uid in cesta else list(cesta.keys())
    for uid in uids:
        for item in cesta.get(uid, {}).get("resultados", []):
            if item.get("id") == item_id:
                item["considerar"] = bool(considerar)
                if justificativa is not None:
                    item["justificativa"] = str(justificativa).strip()
                salvar_cesta(cesta)
                return
    salvar_cesta(cesta)


def finalizar_item(item_uid):
    cesta = obter_cesta()
    if item_uid in cesta:
        cesta[item_uid]["status"] = "finalizado"
        proximo = _proximo_item_uid(cesta, item_uid)
        if proximo:
            _ativar_item(cesta, proximo)
    salvar_cesta(cesta)


def editar_item(item_uid):
    cesta = obter_cesta()
    if item_uid in cesta:
        _ativar_item(cesta, item_uid)
    salvar_cesta(cesta)


def _resumo_valores(resultados, metodologia):
    valores = [
        valor
        for valor in (_preco(item.get("valor_unitario")) for item in resultados if item.get("considerar", True))
        if valor is not None and valor > 0
    ]
    if not valores:
        return {
            "considerados": 0,
            "media": None,
            "mediana": None,
            "menor": None,
            "maior": None,
            "metodologia_formacao_preco": metodologia,
            "valor_final": None,
        }

    media = statistics.mean(valores)
    mediana = statistics.median(valores)
    menor = min(valores)
    maior = max(valores)
    resumo = {
        "considerados": len(valores),
        "media": round(media, 2),
        "mediana": round(mediana, 2),
        "menor": round(menor, 2),
        "maior": round(maior, 2),
        "metodologia_formacao_preco": metodologia,
    }
    resumo["valor_final"] = {
        "media": resumo["media"],
        "mediana": resumo["mediana"],
        "menor_preco": resumo["menor"],
        "combinado": resumo["mediana"] if len(valores) >= 3 else resumo["media"],
    }.get(metodologia, resumo["mediana"])
    return resumo


def resumo_cesta(cesta=None):
    cesta = obter_cesta() if cesta is None else cesta
    resultados = _todos_resultados(cesta)
    metodologia = _metodologia_padrao()
    resumo = _resumo_valores(resultados, metodologia)
    resumo.update({
        "total": len(resultados),
        "itens": len(cesta),
        "itens_finalizados": sum(1 for grupo in cesta.values() if grupo.get("status") == "finalizado"),
        "item_atual_numero": None,
        "total_itens_planejados": int(session.get(TOTAL_ITENS_KEY, 0) or len(cesta)),
    })
    for _, grupo in _ordenar_grupos(cesta):
        if grupo.get("status") == "em_edicao":
            resumo["item_atual_numero"] = grupo.get("numero")
            break
    return resumo


def agrupar_cesta_por_item(cesta=None):
    cesta = obter_cesta() if cesta is None else cesta
    grupos = []
    for _, grupo in _ordenar_grupos(cesta):
        resultados = grupo.get("resultados", [])
        metodologia = grupo.get("metodologia") or _metodologia_padrao()
        resumo = _resumo_valores(resultados, metodologia)
        grupos.append({
            "item_uid": grupo.get("item_uid"),
            "numero": grupo.get("numero"),
            "descricao": grupo.get("descricao") or "Item sem descricao",
            "quantidade": grupo.get("quantidade"),
            "resultados_alvo": grupo.get("resultados_alvo") or len(resultados),
            "status": grupo.get("status", "em_edicao"),
            "finalizado": grupo.get("status") == "finalizado",
            "total": len(resultados),
            "considerados": resumo["considerados"],
            "resumo": resumo,
            "precos": resultados,
        })
    return grupos


def definir_metodologia(metodologia):
    if metodologia not in {"media", "mediana", "menor_preco", "combinado"}:
        metodologia = "mediana"
    session[METODOLOGIA_KEY] = metodologia
    cesta = obter_cesta()
    for grupo in cesta.values():
        grupo["metodologia"] = metodologia
    salvar_cesta(cesta)
