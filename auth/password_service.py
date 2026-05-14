"""Servico de senhas compartilhavel pelas rotas Flask."""

from auth.auth_service import gerar_hash_senha, verificar_senha


__all__ = ["gerar_hash_senha", "verificar_senha"]
