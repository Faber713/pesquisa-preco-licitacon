import secrets
from functools import wraps

from flask import abort, request, session


CSRF_SESSION_KEY = "_csrf_token"


def gerar_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validar_csrf_token(token):
    return bool(token and session.get(CSRF_SESSION_KEY) and token == session.get(CSRF_SESSION_KEY))


def csrf_protect(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not validar_csrf_token(token):
                abort(400)
        return func(*args, **kwargs)

    return wrapper
