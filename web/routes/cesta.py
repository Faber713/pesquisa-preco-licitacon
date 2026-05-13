from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from web.services.cesta_service import (
    adicionar_preco,
    agrupar_cesta_por_item,
    definir_consideracao,
    definir_metodologia,
    editar_item,
    finalizar_item,
    limpar_cesta,
    obter_cesta,
    remover_item,
    remover_preco,
    remover_preco_por_dados,
    resumo_cesta,
)


cesta_bp = Blueprint("cesta", __name__, url_prefix="/cesta")


def _voltar():
    return request.form.get("return_to") or request.referrer or url_for("pesquisa.pesquisa")


def _quer_json():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or "application/json" in request.headers.get("Accept", "")
    )


def _resposta_cesta():
    if not _quer_json():
        return redirect(_voltar())

    itens = obter_cesta()
    resumo = resumo_cesta(itens)
    html = render_template(
        "partials/cesta_panel.html",
        cesta_itens=itens,
        cesta_grupos=agrupar_cesta_por_item(itens),
        cesta_resumo=resumo,
    )
    return jsonify({
        "ok": True,
        "basket_html": html,
        "count": resumo["total"],
        "considerados": resumo["considerados"],
        "valor_final": resumo["valor_final"],
        "metodologia": resumo["metodologia_formacao_preco"],
    })


@cesta_bp.post("/adicionar")
def adicionar():
    adicionar_preco(request.form)
    return _resposta_cesta()


@cesta_bp.post("/remover")
def remover():
    if request.form.get("id"):
        remover_preco(request.form.get("id", ""), request.form.get("item_uid", ""))
    else:
        remover_preco_por_dados(request.form)
    return _resposta_cesta()


@cesta_bp.post("/considerar")
def considerar():
    definir_consideracao(
        request.form.get("id", ""),
        request.form.get("considerar") == "1",
        request.form.get("justificativa", ""),
        request.form.get("item_uid", ""),
    )
    return _resposta_cesta()


@cesta_bp.post("/metodologia")
def metodologia():
    definir_metodologia(request.form.get("metodologia_formacao_preco", "mediana"))
    return _resposta_cesta()


@cesta_bp.post("/finalizar-item")
def finalizar():
    finalizar_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/editar-item")
def editar():
    editar_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/remover-item")
def remover_item_rota():
    remover_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/limpar")
def limpar():
    limpar_cesta()
    return _resposta_cesta()
