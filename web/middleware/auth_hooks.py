from auth.auth_service import carregar_env_local, garantir_admin_configurado


def registrar_auth_hooks(app):
    @app.before_request
    def carregar_contexto_auth():
        carregar_env_local()
        garantir_admin_configurado()
