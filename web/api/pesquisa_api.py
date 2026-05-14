import time

from flask import Blueprint, current_app, jsonify, request

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import registrar_auditoria, salvar_pesquisa_usuario
from utils.util import converter_numero
from web.routes.pesquisa_lote import (
    parse_linhas_lote,
    parse_planilha_lote,
    _limite_resultados,
)
from web.services.filtros_service import (
    filtrar_orgao_origem,
    filtrar_periodo_resultados,
    gerar_item_uid,
    periodo_para_datas,
    preparar_resultados,
)
from web.services.pesquisa_service import executar_pesquisa_item


pesquisa_api_bp = Blueprint("pesquisa_api", __name__, url_prefix="/api")


def _payload():
    return request.get_json(silent=True) or request.form


def _executar(descricao, qtd_min, qtd_max):
    data = _payload()
    if hasattr(data, "getlist"):
        fontes = data.getlist("fontes")
    else:
        fontes = data.get("fontes") if hasattr(data, "get") else None
    if isinstance(fontes, str):
        fontes = [fontes]
    fontes = fontes or ["licitacon"]
    return executar_pesquisa_item(
        descricao,
        qtd_min,
        qtd_max,
        limite=current_app.config["MAX_CANDIDATOS_FLASK"],
        search_db_mode=current_app.config["SEARCH_DB_MODE"],
        raw_path=current_app.config["LICITACON_SQLITE_PATH"],
        operational_path=current_app.config["SEARCH_DB_PATH"],
        fontes=fontes,
    )


def _aplicar_filtros(resultados, data):
    periodo = data.get("periodo_pesquisa", "12m")
    data_inicial_txt = str(data.get("data_inicial", "") or "").strip()
    data_final_txt = str(data.get("data_final", "") or "").strip()
    desconsiderar_orgao = str(data.get("desconsiderar_orgao_origem", "")).lower() in {"1", "true", "on"}
    orgao_origem = str(data.get("orgao_origem", "Prefeitura Municipal de Joia") or "").strip()

    data_inicial, data_final = periodo_para_datas(periodo, data_inicial_txt, data_final_txt)
    resultados, removidos_periodo = filtrar_periodo_resultados(resultados, data_inicial, data_final)
    resultados, removidos_orgao = filtrar_orgao_origem(
        resultados,
        orgao_origem,
        desconsiderar_orgao,
    )
    return resultados, removidos_periodo, removidos_orgao


@pesquisa_api_bp.get("/status")
def status():
    return jsonify({
        "ok": True,
        "app": current_app.config["APP_NAME"],
        "search_db_mode": current_app.config["SEARCH_DB_MODE"],
        "raw_path": current_app.config["LICITACON_SQLITE_PATH"],
        "operational_path": current_app.config["SEARCH_DB_PATH"],
    })


@pesquisa_api_bp.post("/pesquisa")
@login_required
def pesquisa():
    data = _payload()
    descricao = str(data.get("descricao", "") or "").strip()
    qtd_min = converter_numero(data.get("qtd_min", "1"))
    qtd_max = converter_numero(data.get("qtd_max", "999999"))
    resultados_max = converter_numero(data.get("resultados_max", "50")) or 50
    resultados_max = max(1, min(int(resultados_max), 100))

    if not descricao:
        return jsonify({"ok": False, "erro": "Informe a descricao do item."}), 400
    if qtd_min is None or qtd_max is None:
        return jsonify({"ok": False, "erro": "Informe quantidades validas."}), 400
    if qtd_min > qtd_max:
        return jsonify({"ok": False, "erro": "A quantidade minima nao pode ser maior que a maxima."}), 400

    criterios, resultados, estatisticas = _executar(descricao, qtd_min, qtd_max)
    resultados, removidos_periodo, removidos_orgao = _aplicar_filtros(resultados, data)
    item_uid = gerar_item_uid(descricao, f"{qtd_min}-{qtd_max}")
    resultados = preparar_resultados(resultados, item_uid)

    estatisticas["filtrados_orgao_origem"] = removidos_orgao
    estatisticas["filtrados_periodo"] = removidos_periodo
    estatisticas["total_exibido"] = len(resultados)

    payload_resposta = {
        "ok": True,
        "item_uid": item_uid,
        "criterios": criterios,
        "estatisticas": estatisticas,
        "resultados": resultados[:resultados_max],
    }
    usuario = usuario_atual()
    if usuario:
        pesquisa_id = salvar_pesquisa_usuario(
            usuario.get("id"),
            descricao,
            estatisticas.get("fontes", []),
            "auto",
            payload_resposta,
        )
        registrar_auditoria(
            usuario.get("id"),
            "pesquisa",
            "pesquisas",
            pesquisa_id,
            {"descricao": descricao, "fontes": estatisticas.get("fontes", [])},
            request.remote_addr,
        )
        payload_resposta["pesquisa_id"] = pesquisa_id

    return jsonify(payload_resposta)


@pesquisa_api_bp.post("/lote")
@login_required
def lote():
    data = _payload()
    texto_lote = str(data.get("itens_lote", "") or "")
    quantidade_resultados = _limite_resultados(data.get("quantidade_resultados", 8))
    if texto_lote.strip():
        itens, erros = parse_linhas_lote(texto_lote)
    else:
        itens, erros, _, _ = parse_planilha_lote(request.form)

    inicio_lote = time.perf_counter()
    resultados_lote = []
    for item in itens:
        inicio_item = time.perf_counter()
        try:
            criterios, resultados, estatisticas = _executar(
                item["descricao"],
                item["qtd_min"],
                item["qtd_max"],
            )
            resultados, removidos_periodo, removidos_orgao = _aplicar_filtros(resultados, data)
            resultados = preparar_resultados(resultados, item["item_uid"])
            estatisticas["filtrados_orgao_origem"] = removidos_orgao
            estatisticas["filtrados_periodo"] = removidos_periodo
            estatisticas["total_exibido"] = len(resultados)
            resultados_lote.append({
                "item": item,
                "criterios": criterios,
                "resultados": resultados[:quantidade_resultados],
                "estatisticas": estatisticas,
                "tempo_item_ms": round((time.perf_counter() - inicio_item) * 1000, 2),
                "erro": "",
            })
        except Exception as erro:
            resultados_lote.append({
                "item": item,
                "criterios": None,
                "resultados": [],
                "estatisticas": None,
                "tempo_item_ms": round((time.perf_counter() - inicio_item) * 1000, 2),
                "erro": str(erro),
            })

    sucesso = sum(1 for bloco in resultados_lote if not bloco["erro"])
    return jsonify({
        "ok": True,
        "erros": erros,
        "resultados_lote": resultados_lote,
        "resumo": {
            "itens_validos": len(itens),
            "sucesso": sucesso,
            "erros": len(erros) + (len(resultados_lote) - sucesso),
            "tempo_total_ms": round((time.perf_counter() - inicio_lote) * 1000, 2),
        },
    })
