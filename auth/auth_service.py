import hashlib
import hmac
import os
import secrets

from storage.app_storage import (
    buscar_usuario_por_email,
    contar_usuarios,
    criar_usuario,
    registrar_auditoria,
    registrar_login_usuario,
)


ITERACOES_HASH = 260_000


def carregar_env_local(caminho=".env"):
    if not os.path.exists(caminho):
        return
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
    except OSError:
        pass


def config(chave, padrao=""):
    return os.getenv(chave, padrao)


def auth_habilitado():
    valor = str(config("APP_AUTH_ENABLED", "1")).strip().lower()
    return valor not in {"0", "false", "nao", "no", "off"}


def gerar_hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        senha.encode("utf-8"),
        salt.encode("utf-8"),
        ITERACOES_HASH,
    ).hex()
    return f"pbkdf2_sha256${ITERACOES_HASH}${salt}${digest}"


def verificar_senha(senha, senha_hash):
    try:
        algoritmo, iteracoes, salt, digest = senha_hash.split("$", 3)
        if algoritmo != "pbkdf2_sha256":
            return False
        novo_digest = hashlib.pbkdf2_hmac(
            "sha256",
            senha.encode("utf-8"),
            salt.encode("utf-8"),
            int(iteracoes),
        ).hex()
        return hmac.compare_digest(novo_digest, digest)
    except Exception:
        return False


def garantir_admin_configurado():
    if contar_usuarios() > 0:
        return

    email = str(config("APP_ADMIN_EMAIL", "")).strip().lower()
    senha = str(config("APP_ADMIN_PASSWORD", "")).strip()
    nome = str(config("APP_ADMIN_NAME", "Administrador")).strip() or "Administrador"
    if email and senha:
        usuario_id = criar_usuario(nome, email, gerar_hash_senha(senha), perfil="admin", ativo=True)
        registrar_auditoria(usuario_id, "admin_inicial_criado", "usuarios", usuario_id, {"email": email})


def autenticar_usuario(email, senha):
    usuario = buscar_usuario_por_email(email or "")
    if not usuario or not usuario.get("ativo"):
        return None
    if not verificar_senha(senha or "", usuario.get("senha_hash", "")):
        return None

    registrar_login_usuario(usuario["id"])
    registrar_auditoria(usuario["id"], "login", "usuarios", usuario["id"], {"email": usuario["email"]})
    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "email": usuario["email"],
        "perfil": usuario["perfil"],
    }
