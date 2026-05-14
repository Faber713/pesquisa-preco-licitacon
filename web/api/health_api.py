import sqlite3
import time

from flask import Blueprint, current_app, jsonify

from config.runtime_settings import APP_STARTED_AT, APP_VERSION
from ia.ia_cache import cache_ia_ok
from ia.ia_criterios import status_openai_local
from search.sqlite_repository import base_sqlite_disponivel
from services.pncp_client import PNCPClient
from storage.app_storage import CAMINHO_APP_DB


health_api_bp = Blueprint("health_api", __name__, url_prefix="/api")


def _sqlite_app_status():
    try:
        with sqlite3.connect(CAMINHO_APP_DB) as con:
            con.execute("SELECT 1").fetchone()
        return "ok"
    except Exception as erro:
        return f"erro: {erro}"


@health_api_bp.get("/health")
def health():
    operational_ok, operational_erro = base_sqlite_disponivel(
        current_app.config["SEARCH_DB_PATH"],
        tabela="base_pesquisa",
    )
    return jsonify(
        {
            "flask": "ok",
            "sqlite_operational": "ok" if operational_ok else f"erro: {operational_erro}",
            "sqlite_app": _sqlite_app_status(),
            "pncp": PNCPClient.status_pncp_local(),
            "openai": status_openai_local(),
            "cache_ia": "ok" if cache_ia_ok() else "erro",
            "uptime": round(time.time() - APP_STARTED_AT, 2),
            "version": APP_VERSION,
        }
    )
