from flask import Blueprint, current_app, redirect, render_template, request, url_for

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import (
    atualizar_cotacao_operacional,
    atualizar_status_cotacao,
    criar_cotacao_operacional,
    excluir_cotacao_operacional,
    listar_cotacoes_operacionais,
    registrar_auditoria,
)


cotacoes_bp = Blueprint("cotacoes", __name__, url_prefix="/cotacoes")


@cotacoes_bp.get("")
@cotacoes_bp.get("/")
@login_required
def listar():
    usuario = usuario_atual() or {}
    cotacoes = listar_cotacoes_operacionais(usuario.get("id"))
    return render_template(
        "cotacoes.html",
        app_name=current_app.config["APP_NAME"],
        page_title="Minhas cotacoes",
        cotacoes=cotacoes,
    )


@cotacoes_bp.post("")
@cotacoes_bp.post("/")
@login_required
def criar():
    usuario = usuario_atual() or {}
    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()
    cotacao_id = criar_cotacao_operacional(nome, categoria, usuario.get("id"))
    registrar_auditoria(
        usuario.get("id"),
        "cotacao_criar",
        "cotacoes",
        cotacao_id,
        {"nome": nome, "categoria": categoria},
        request.remote_addr,
    )
    return redirect(url_for("pesquisa_lote.pesquisa_lote", cotacao_id=cotacao_id))


@cotacoes_bp.post("/<int:cotacao_id>/editar")
@login_required
def editar(cotacao_id):
    usuario = usuario_atual() or {}
    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()
    atualizado = atualizar_cotacao_operacional(cotacao_id, nome, categoria, usuario.get("id"))
    if atualizado:
        registrar_auditoria(
            usuario.get("id"),
            "cotacao_editar",
            "cotacoes",
            cotacao_id,
            {"nome": nome, "categoria": categoria},
            request.remote_addr,
        )
    return redirect(url_for("cotacoes.listar"))


@cotacoes_bp.post("/<int:cotacao_id>/status")
@login_required
def status(cotacao_id):
    usuario = usuario_atual() or {}
    novo_status = request.form.get("status", "")
    atualizado = atualizar_status_cotacao(cotacao_id, novo_status, usuario.get("id"))
    if atualizado:
        registrar_auditoria(
            usuario.get("id"),
            "cotacao_status",
            "cotacoes",
            cotacao_id,
            {"status": novo_status},
            request.remote_addr,
        )
    return redirect(url_for("cotacoes.listar"))


@cotacoes_bp.post("/<int:cotacao_id>/excluir")
@login_required
def excluir(cotacao_id):
    usuario = usuario_atual() or {}
    removida = excluir_cotacao_operacional(cotacao_id, usuario.get("id"))
    if removida:
        registrar_auditoria(
            usuario.get("id"),
            "cotacao_excluir",
            "cotacoes",
            cotacao_id,
            {},
            request.remote_addr,
        )
    return redirect(url_for("cotacoes.listar"))
