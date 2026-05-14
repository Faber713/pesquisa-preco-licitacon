from flask import Blueprint, jsonify, request

from web.services.filtros_service import periodo_para_datas


filtros_api_bp = Blueprint("filtros_api", __name__, url_prefix="/api/filtros")


@filtros_api_bp.get("/periodo")
def periodo():
    data_inicial, data_final = periodo_para_datas(
        request.args.get("periodo_pesquisa", "12m"),
        request.args.get("data_inicial", ""),
        request.args.get("data_final", ""),
    )
    return jsonify({
        "ok": True,
        "data_inicial": data_inicial.isoformat() if data_inicial else "",
        "data_final": data_final.isoformat() if data_final else "",
    })
