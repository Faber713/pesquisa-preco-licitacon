import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth.auth_service import autenticar_usuario
from auth.csrf import csrf_protect
from auth.session_manager import encerrar_sessao, iniciar_sessao, usuario_atual
from storage.app_storage import registrar_auditoria


auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger("app")


@auth_bp.route("/login", methods=["GET", "POST"])
@csrf_protect
def login():
    if usuario_atual():
        return redirect(url_for("main.index"))

    erro = ""
    next_url = request.args.get("next") or request.form.get("next") or url_for("main.index")
    if request.method == "POST":
        usuario = autenticar_usuario(
            request.form.get("email", ""),
            request.form.get("senha", ""),
        )
        if usuario:
            iniciar_sessao(usuario)
            logger.info("login_ok usuario_id=%s email=%s ip=%s", usuario.get("id"), usuario.get("email"), request.remote_addr)
            return redirect(next_url or url_for("main.index"))
        logger.warning("login_falha email=%s ip=%s", request.form.get("email", ""), request.remote_addr)
        erro = "Email ou senha invalidos."

    return render_template("login.html", erro=erro, next_url=next_url, status="Login")


@auth_bp.post("/logout")
@csrf_protect
def logout():
    usuario = usuario_atual()
    if usuario:
        logger.info("logout usuario_id=%s email=%s ip=%s", usuario.get("id"), usuario.get("email"), request.remote_addr)
        registrar_auditoria(
            usuario.get("id"),
            "logout",
            "usuarios",
            usuario.get("id"),
            {"email": usuario.get("email")},
            request.remote_addr,
        )
    encerrar_sessao()
    flash("Sessao encerrada.")
    return redirect(url_for("auth.login"))
