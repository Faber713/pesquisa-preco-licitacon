import os
import logging
import time

from flask import Flask, g, request, session
from werkzeug.exceptions import HTTPException

from config.logging_config import setup_logging
from config.search_settings import carregar_search_db_config
from storage.app_storage import inicializar_app_db
from config.runtime_settings import (
    CACHE_FOLDER,
    DEBUG_LOGS,
    LOG_FOLDER,
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    UPLOAD_FOLDER,
)
from auth.csrf import gerar_csrf_token
from utils.util import formatar_moeda_br, formatar_percentual
from web.api.cesta_api import cesta_api_bp
from web.api.dossie_api import dossie_api_bp
from web.api.filtros_api import filtros_api_bp
from web.api.health_api import health_api_bp
from web.api.pesquisa_api import pesquisa_api_bp
from web.routes.cesta import cesta_bp
from web.routes.cotacoes import cotacoes_bp
from web.routes.dossie import dossie_bp
from web.routes.auth import auth_bp
from web.routes.admin import admin_bp
from web.routes.main import main_bp
from web.routes.pesquisa import pesquisa_bp
from web.routes.pesquisa_lote import pesquisa_lote_bp
from web.middleware.auth_hooks import registrar_auth_hooks
from web.services.cesta_service import agrupar_cesta_por_item, obter_cesta, resumo_cesta


setup_logging(DEBUG_LOGS)
app_logger = logging.getLogger("app")
errors_logger = logging.getLogger("errors")


def create_app():
    inicializar_app_db()
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app_logger.info("Inicializando Flask app=%s debug_logs=%s", "Pesquisa Inteligente de Precos", DEBUG_LOGS)
    app.config["APP_NAME"] = "Pesquisa Inteligente de Precos"
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-cesta-precos-local")
    app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_HTTPONLY"] = SESSION_COOKIE_HTTPONLY
    app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["LOG_FOLDER"] = LOG_FOLDER
    app.config["CACHE_FOLDER"] = CACHE_FOLDER
    search_db = carregar_search_db_config(os.getenv)
    app.config["SEARCH_DB_MODE"] = search_db.mode
    app.config["SEARCH_DB_PATH"] = search_db.operational_path
    app.config["LICITACON_SQLITE_PATH"] = search_db.raw_path
    app.config["MAX_CANDIDATOS_FLASK"] = int(os.getenv("MAX_CANDIDATOS_FLASK", "1200"))
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cesta_bp)
    app.register_blueprint(cotacoes_bp)
    app.register_blueprint(dossie_bp)
    app.register_blueprint(pesquisa_bp)
    app.register_blueprint(pesquisa_lote_bp)
    app.register_blueprint(health_api_bp)
    app.register_blueprint(pesquisa_api_bp)
    app.register_blueprint(cesta_api_bp)
    app.register_blueprint(dossie_api_bp)
    app.register_blueprint(filtros_api_bp)
    registrar_auth_hooks(app)
    app.add_template_filter(formatar_moeda_br, "moeda_br")
    app.add_template_filter(formatar_percentual, "percentual")

    @app.before_request
    def iniciar_metrica_request():
        g.request_started_at = time.perf_counter()

    @app.after_request
    def registrar_metrica_request(response):
        inicio = getattr(g, "request_started_at", None)
        tempo_ms = round((time.perf_counter() - inicio) * 1000, 2) if inicio else 0
        app_logger.info(
            "request metodo=%s path=%s endpoint=%s status=%s tempo_ms=%s ip=%s",
            request.method,
            request.path,
            request.endpoint,
            response.status_code,
            tempo_ms,
            request.remote_addr,
        )
        return response

    @app.errorhandler(Exception)
    def registrar_erro_global(erro):
        if isinstance(erro, HTTPException):
            return erro
        errors_logger.exception(
            "erro_global path=%s metodo=%s endpoint=%s",
            request.path,
            request.method,
            request.endpoint,
        )
        return "Erro interno do servidor", 500

    @app.context_processor
    def inject_cesta():
        itens = obter_cesta()
        return {
            "cesta_itens": itens,
            "cesta_grupos": agrupar_cesta_por_item(itens),
            "cesta_resumo": resumo_cesta(itens),
            "usuario_logado": session.get("usuario_logado"),
            "csrf_token": gerar_csrf_token,
        }

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
