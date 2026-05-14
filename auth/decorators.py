"""Decorators de autenticacao/autorizacao para Flask."""

from functools import wraps

from flask import abort, jsonify, redirect, request, session, url_for

from auth.auth_service import auth_habilitado
from auth.permissions import is_admin


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not auth_habilitado() or session.get("usuario_logado"):
            return func(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "erro": "Login requerido."}), 401
        return redirect(url_for("auth.login", next=request.path))

    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not auth_habilitado():
            return func(*args, **kwargs)
        usuario = session.get("usuario_logado")
        if not usuario:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "erro": "Login requerido."}), 401
            return redirect(url_for("auth.login", next=request.path))
        if not is_admin(usuario):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "erro": "Permissao negada."}), 403
            abort(403)
        return func(*args, **kwargs)

    return wrapper
