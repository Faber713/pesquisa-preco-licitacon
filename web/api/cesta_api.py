from flask import Blueprint, jsonify, render_template

from auth.decorators import login_required
from web.services.cesta_service import agrupar_cesta_por_item, obter_cesta, resumo_cesta


cesta_api_bp = Blueprint("cesta_api", __name__, url_prefix="/api/cesta")


@cesta_api_bp.get("")
@cesta_api_bp.get("/")
@login_required
def detalhe_cesta():
    itens = obter_cesta()
    resumo = resumo_cesta(itens)
    return jsonify({
        "ok": True,
        "itens": itens,
        "resumo": resumo,
        "basket_html": render_template(
            "partials/cesta_panel.html",
            cesta_itens=itens,
            cesta_grupos=agrupar_cesta_por_item(itens),
            cesta_resumo=resumo,
        ),
    })
