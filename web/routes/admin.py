from flask import Blueprint, abort, redirect, render_template, request, url_for

from auth.csrf import csrf_protect
from auth.decorators import admin_required
from auth.password_service import gerar_hash_senha
from auth.session_manager import usuario_atual
from storage.app_storage import (
    atualizar_senha_usuario,
    atualizar_usuario,
    buscar_usuario_por_id,
    criar_usuario,
    listar_auditoria,
    listar_usuarios,
    registrar_auditoria,
)


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/")
@admin_required
def painel():
    return render_template(
        "admin/index.html",
        usuarios_total=len(listar_usuarios()),
        auditoria=listar_auditoria(limite=10),
        status="Admin",
    )


@admin_bp.get("/usuarios")
@admin_required
def usuarios():
    return render_template("admin/usuarios.html", usuarios=listar_usuarios(), status="Usuarios")


@admin_bp.route("/usuarios/novo", methods=["GET", "POST"])
@admin_required
@csrf_protect
def novo_usuario():
    erro = ""
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        perfil = request.form.get("perfil", "usuario")
        ativo = request.form.get("ativo") == "1"
        if not nome or "@" not in email:
            erro = "Informe nome e email valido."
        elif len(senha) < 8:
            erro = "A senha deve ter pelo menos 8 caracteres."
        else:
            usuario_id = criar_usuario(nome, email, gerar_hash_senha(senha), perfil=perfil, ativo=ativo)
            atual = usuario_atual()
            registrar_auditoria(
                atual.get("id") if atual else None,
                "usuario_criado",
                "usuarios",
                usuario_id,
                {"email": email, "perfil": perfil, "ativo": ativo},
                request.remote_addr,
            )
            return redirect(url_for("admin.usuarios"))

    return render_template("admin/usuario_form.html", usuario=None, erro=erro, status="Novo usuario")


@admin_bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@admin_required
@csrf_protect
def editar_usuario(usuario_id):
    usuario = buscar_usuario_por_id(usuario_id)
    if not usuario:
        abort(404)
    erro = ""
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        perfil = request.form.get("perfil", "usuario")
        ativo = request.form.get("ativo") == "1"
        nova_senha = request.form.get("senha", "")
        if not nome or "@" not in email:
            erro = "Informe nome e email valido."
        elif nova_senha and len(nova_senha) < 8:
            erro = "A nova senha deve ter pelo menos 8 caracteres."
        else:
            atualizar_usuario(usuario_id, nome, email, perfil, ativo)
            if nova_senha:
                atualizar_senha_usuario(usuario_id, gerar_hash_senha(nova_senha))
            atual = usuario_atual()
            registrar_auditoria(
                atual.get("id") if atual else None,
                "usuario_editado",
                "usuarios",
                usuario_id,
                {"email": email, "perfil": perfil, "ativo": ativo, "reset_senha": bool(nova_senha)},
                request.remote_addr,
            )
            return redirect(url_for("admin.usuarios"))

    return render_template("admin/usuario_form.html", usuario=usuario, erro=erro, status="Editar usuario")


@admin_bp.get("/auditoria")
@admin_required
def auditoria():
    return render_template("admin/auditoria.html", eventos=listar_auditoria(limite=250), status="Auditoria")
