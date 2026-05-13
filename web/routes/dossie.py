from flask import Blueprint, render_template, request

from reports.dossie_service import gerar_dossie_contexto


dossie_bp = Blueprint("dossie", __name__, url_prefix="/dossie")


@dossie_bp.get("/")
def dossie():
    contexto = gerar_dossie_contexto(
        servidor_responsavel=request.args.get("servidor_responsavel", ""),
    )
    return render_template("dossie.html", **contexto)
