"""Permissoes e perfis de acesso da aplicacao."""


PERFIL_ADMIN = "admin"
PERFIL_USUARIO = "usuario"


def is_admin(usuario):
    return bool(usuario and usuario.get("perfil") == PERFIL_ADMIN)


def pode_acessar_admin(usuario):
    return is_admin(usuario)


def pode_ver_auditoria(usuario):
    return is_admin(usuario)
