from flask import Blueprint, jsonify, request

from auth.decorators import login_required
from reports.dossie_service import gerar_dossie_contexto


dossie_api_bp = Blueprint("dossie_api", __name__, url_prefix="/api/dossie")


@dossie_api_bp.get("")
@dossie_api_bp.get("/")
@login_required
def dossie():
    contexto = gerar_dossie_contexto(
        servidor_responsavel=request.args.get("servidor_responsavel", ""),
    )
    return jsonify({"ok": True, "dossie": contexto})
