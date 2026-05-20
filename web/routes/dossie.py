from flask import Blueprint, render_template, request

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import registrar_auditoria
from reports.dossie_service import gerar_dossie_contexto


dossie_bp = Blueprint("dossie", __name__, url_prefix="/dossie")


@dossie_bp.get("/")
@login_required
def dossie():
    usuario = usuario_atual()
    if usuario:
        registrar_auditoria(usuario.get("id"), "dossie", "dossie", "", {}, request.remote_addr)
    contexto = gerar_dossie_contexto(
        servidor_responsavel=request.args.get("servidor_responsavel", ""),
    )
    return render_template("dossie.html", **contexto)
