from flask import Blueprint, current_app, render_template, request

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import registrar_auditoria, salvar_pesquisa_usuario
from utils.util import converter_numero
from web.services.filtros_service import (
    filtrar_orgao_origem,
    filtrar_periodo_resultados,
    gerar_item_uid,
    periodo_para_datas,
    preparar_resultados,
)
from web.services.pesquisa_service import executar_pesquisa_item


pesquisa_bp = Blueprint("pesquisa", __name__, url_prefix="/pesquisa")


def _executar_pesquisa_sqlite(descricao, qtd_min, qtd_max):
    fontes = request.form.getlist("fontes") or ["licitacon"]
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


@pesquisa_bp.route("/", methods=["GET", "POST"])
@login_required
def pesquisa():
    contexto = {
        "app_name": current_app.config["APP_NAME"],
        "status": "Busca LicitaCon",
        "form": {
            "descricao": "",
            "qtd_min": "1",
            "qtd_max": "999999",
            "desconsiderar_orgao_origem": "",
            "orgao_origem": "Prefeitura Municipal de Jóia",
            "periodo_pesquisa": "12m",
            "data_inicial": "",
            "data_final": "",
            "resultados_max": "50",
            "fontes": ["licitacon"],
        },
        "item_uid": "",
        "criterios": None,
        "resultados": [],
        "estatisticas": None,
        "erro": "",
    }

    if request.method == "GET":
        return render_template("pesquisa.html", **contexto)

    descricao = request.form.get("descricao", "").strip()
    qtd_min_txt = request.form.get("qtd_min", "").strip()
    qtd_max_txt = request.form.get("qtd_max", "").strip()
    desconsiderar_orgao_origem = request.form.get("desconsiderar_orgao_origem") == "1"
    orgao_origem = request.form.get("orgao_origem", "Prefeitura Municipal de Jóia").strip()
    periodo_pesquisa = request.form.get("periodo_pesquisa", "12m")
    data_inicial_txt = request.form.get("data_inicial", "").strip()
    data_final_txt = request.form.get("data_final", "").strip()
    resultados_max_txt = request.form.get("resultados_max", "50").strip()
    fontes = request.form.getlist("fontes") or ["licitacon"]
    contexto["form"] = {
        "descricao": descricao,
        "qtd_min": qtd_min_txt,
        "qtd_max": qtd_max_txt,
        "desconsiderar_orgao_origem": "1" if desconsiderar_orgao_origem else "",
        "orgao_origem": orgao_origem,
        "periodo_pesquisa": periodo_pesquisa,
        "data_inicial": data_inicial_txt,
        "data_final": data_final_txt,
        "resultados_max": resultados_max_txt,
        "fontes": fontes,
    }

    qtd_min = converter_numero(qtd_min_txt)
    qtd_max = converter_numero(qtd_max_txt)

    if not descricao:
        contexto["erro"] = "Informe a descricao do item."
        return render_template("pesquisa.html", **contexto), 400
    if qtd_min is None or qtd_max is None:
        contexto["erro"] = "Informe quantidades validas."
        return render_template("pesquisa.html", **contexto), 400
    if qtd_min > qtd_max:
        contexto["erro"] = "A quantidade minima nao pode ser maior que a maxima."
        return render_template("pesquisa.html", **contexto), 400
    resultados_max = converter_numero(resultados_max_txt) or 50
    resultados_max = max(1, min(int(resultados_max), 100))

    try:
        criterios, resultados, estatisticas = _executar_pesquisa_sqlite(
            descricao,
            qtd_min,
            qtd_max,
        )
    except Exception as erro:
        contexto["erro"] = f"Nao foi possivel executar a pesquisa: {erro}"
        return render_template("pesquisa.html", **contexto), 500

    if estatisticas.get("erro"):
        contexto["erro"] = estatisticas["erro"]
    data_inicial, data_final = periodo_para_datas(periodo_pesquisa, data_inicial_txt, data_final_txt)
    resultados, removidos_periodo = filtrar_periodo_resultados(resultados, data_inicial, data_final)
    resultados, removidos_orgao = filtrar_orgao_origem(
        resultados,
        orgao_origem,
        desconsiderar_orgao_origem,
    )
    item_uid = gerar_item_uid(descricao, f"{qtd_min_txt}-{qtd_max_txt}")
    resultados = preparar_resultados(resultados, item_uid)
    estatisticas["filtrados_orgao_origem"] = removidos_orgao
    estatisticas["filtrados_periodo"] = removidos_periodo
    estatisticas["total_exibido"] = len(resultados)
    contexto["criterios"] = criterios
    contexto["item_uid"] = item_uid
    contexto["resultados"] = resultados[:resultados_max]
    contexto["estatisticas"] = estatisticas
    usuario = usuario_atual()
    if usuario:
        pesquisa_id = salvar_pesquisa_usuario(
            usuario.get("id"),
            descricao,
            fontes,
            "auto",
            {
                "criterios": criterios,
                "estatisticas": estatisticas,
                "resultados": resultados[:resultados_max],
            },
        )
        registrar_auditoria(
            usuario.get("id"),
            "pesquisa",
            "pesquisas",
            pesquisa_id,
            {"descricao": descricao, "fontes": fontes},
            request.remote_addr,
        )
        contexto["pesquisa_id"] = pesquisa_id
    return render_template("pesquisa.html", **contexto)
