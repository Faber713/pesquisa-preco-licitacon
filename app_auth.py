import hashlib
import hmac
import os
import secrets

import streamlit as st

from app_storage import (
    buscar_usuario_por_email,
    contar_usuarios,
    criar_usuario,
    registrar_login_usuario,
)


ITERACOES_HASH = 260_000


def _carregar_env_local():
    if not os.path.exists(".env"):
        return
    try:
        with open(".env", "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
    except OSError:
        pass


def _config(chave, padrao=""):
    if os.getenv(chave) is not None:
        return os.getenv(chave, padrao)
    try:
        return st.secrets.get(chave, padrao)
    except Exception:
        return padrao


def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def auth_habilitado():
    valor = str(_config("APP_AUTH_ENABLED", "1")).strip().lower()
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

    email = str(_config("APP_ADMIN_EMAIL", "")).strip().lower()
    senha = str(_config("APP_ADMIN_PASSWORD", "")).strip()
    nome = str(_config("APP_ADMIN_NAME", "Administrador")).strip() or "Administrador"
    if email and senha:
        criar_usuario(nome, email, gerar_hash_senha(senha), perfil="admin", ativo=True)


def _render_setup_primeiro_admin():
    st.title("Configurar acesso inicial")
    st.caption("Crie o primeiro usuario administrador para proteger a aplicacao.")

    with st.form("setup_primeiro_admin"):
        nome = st.text_input("Nome", value="Administrador")
        email = st.text_input("Email")
        senha = st.text_input("Senha", type="password")
        confirmar = st.text_input("Confirmar senha", type="password")
        enviar = st.form_submit_button("Criar administrador", type="primary", use_container_width=True)

    if not enviar:
        st.info(
            "Em hospedagem publica, prefira configurar APP_ADMIN_EMAIL e APP_ADMIN_PASSWORD "
            "nos secrets antes do primeiro acesso."
        )
        return None

    if not email.strip() or "@" not in email:
        st.error("Informe um email valido.")
        return None
    if len(senha) < 8:
        st.error("Use uma senha com pelo menos 8 caracteres.")
        return None
    if senha != confirmar:
        st.error("As senhas nao conferem.")
        return None

    criar_usuario(nome.strip() or "Administrador", email, gerar_hash_senha(senha), perfil="admin")
    st.success("Administrador criado. Entre com o email e senha cadastrados.")
    _rerun()
    return None


def _render_login():
    st.title("Entrar")
    st.caption("Acesse a Pesquisa Inteligente LicitaCon.")

    with st.form("form_login"):
        email = st.text_input("Email")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if not entrar:
        return None

    usuario = buscar_usuario_por_email(email)
    if not usuario or not usuario.get("ativo") or not verificar_senha(senha, usuario.get("senha_hash", "")):
        st.error("Email ou senha invalidos.")
        return None

    registrar_login_usuario(usuario["id"])
    st.session_state["usuario_logado"] = {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "email": usuario["email"],
        "perfil": usuario["perfil"],
    }
    _rerun()
    return None


def exigir_login():
    _carregar_env_local()
    if not auth_habilitado():
        return {"id": None, "nome": "Modo local", "email": "local", "perfil": "admin"}

    garantir_admin_configurado()

    usuario = st.session_state.get("usuario_logado")
    if usuario:
        with st.sidebar:
            st.caption(f"Conectado: {usuario.get('nome')}")
            if st.button("Sair", use_container_width=True):
                st.session_state.pop("usuario_logado", None)
                _rerun()
        return usuario

    if contar_usuarios() == 0:
        _render_setup_primeiro_admin()
    else:
        _render_login()
    return None
