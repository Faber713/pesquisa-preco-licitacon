"""Gerenciamento de sessao Flask."""

from flask import session

from storage.app_storage import buscar_usuario_por_id

def usuario_atual():
    return session.get("usuario_logado")


def usuario_atual_completo():
    usuario = usuario_atual()
    if not usuario:
        return None
    return buscar_usuario_por_id(usuario.get("id"))


def iniciar_sessao(usuario):
    session["usuario_logado"] = usuario


def encerrar_sessao():
    session.pop("usuario_logado", None)
