import os

from flask import Flask

from utils.search_config import carregar_search_db_config
from utils.util import formatar_moeda_br, formatar_percentual
from web.routes.cesta import cesta_bp
from web.routes.dossie import dossie_bp
from web.routes.main import main_bp
from web.routes.pesquisa import pesquisa_bp
from web.routes.pesquisa_lote import pesquisa_lote_bp
from web.services.cesta_service import agrupar_cesta_por_item, obter_cesta, resumo_cesta


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["APP_NAME"] = "Pesquisa Inteligente de Precos"
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-cesta-precos-local")
    search_db = carregar_search_db_config(os.getenv)
    app.config["SEARCH_DB_MODE"] = search_db.mode
    app.config["SEARCH_DB_PATH"] = search_db.operational_path
    app.config["LICITACON_SQLITE_PATH"] = search_db.raw_path
    app.config["MAX_CANDIDATOS_FLASK"] = int(os.getenv("MAX_CANDIDATOS_FLASK", "1200"))
    app.register_blueprint(main_bp)
    app.register_blueprint(cesta_bp)
    app.register_blueprint(dossie_bp)
    app.register_blueprint(pesquisa_bp)
    app.register_blueprint(pesquisa_lote_bp)
    app.add_template_filter(formatar_moeda_br, "moeda_br")
    app.add_template_filter(formatar_percentual, "percentual")

    @app.context_processor
    def inject_cesta():
        itens = obter_cesta()
        return {
            "cesta_itens": itens,
            "cesta_grupos": agrupar_cesta_por_item(itens),
            "cesta_resumo": resumo_cesta(itens),
        }

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
