from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import obter_cotacao_operacional, registrar_auditoria, salvar_workspace_cotacao
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
COTACAO_ATIVA_KEY = "cotacao_operacional_ativa_id"


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


def _autosave_resultado_cotacao(dados, selecionado=True):
    cotacao_id = session.get(COTACAO_ATIVA_KEY)
    if not cotacao_id:
        return
    usuario = usuario_atual() or {}
    cotacao = obter_cotacao_operacional(cotacao_id, usuario.get("id"))
    if not cotacao:
        return
    workspace = cotacao.get("workspace") or {}
    item_uid = dados.get("item_uid", "")
    resultado_uid = dados.get("resultado_uid") or dados.get("id") or ""
    for item in workspace.get("itens", []):
        if item.get("item_uid") != item_uid:
            continue
        selecionados = item.setdefault("resultados_selecionados", [])
        if selecionado:
            payload = dict(dados)
            payload["id"] = resultado_uid
            if not any(r.get("id") == resultado_uid for r in selecionados):
                selecionados.append(payload)
            for resultado in item.get("resultados", []):
                if resultado.get("resultado_uid") == resultado_uid:
                    resultado["selecionado"] = True
        else:
            item["resultados_selecionados"] = [
                r for r in selecionados if r.get("id") != resultado_uid
            ]
            for resultado in item.get("resultados", []):
                if resultado.get("resultado_uid") == resultado_uid:
                    resultado["selecionado"] = False
        salvar_workspace_cotacao(cotacao_id, workspace, item_uid, usuario.get("id"))
        return


@cesta_bp.post("/adicionar")
@login_required
def adicionar():
    adicionar_preco(request.form)
    _autosave_resultado_cotacao(request.form, True)
    usuario = usuario_atual()
    if usuario:
        registrar_auditoria(usuario.get("id"), "cesta_adicionar", "cesta", request.form.get("item_uid", ""), dict(request.form), request.remote_addr)
    return _resposta_cesta()


@cesta_bp.post("/remover")
@login_required
def remover():
    if request.form.get("id"):
        remover_preco(request.form.get("id", ""), request.form.get("item_uid", ""))
    else:
        remover_preco_por_dados(request.form)
    _autosave_resultado_cotacao(request.form, False)
    return _resposta_cesta()


@cesta_bp.post("/considerar")
@login_required
def considerar():
    definir_consideracao(
        request.form.get("id", ""),
        request.form.get("considerar") == "1",
        request.form.get("justificativa", ""),
        request.form.get("item_uid", ""),
    )
    return _resposta_cesta()


@cesta_bp.post("/metodologia")
@login_required
def metodologia():
    definir_metodologia(request.form.get("metodologia_formacao_preco", "mediana"))
    return _resposta_cesta()


@cesta_bp.post("/finalizar-item")
@login_required
def finalizar():
    finalizar_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/editar-item")
@login_required
def editar():
    editar_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/remover-item")
@login_required
def remover_item_rota():
    remover_item(request.form.get("item_uid", ""))
    return _resposta_cesta()


@cesta_bp.post("/limpar")
@login_required
def limpar():
    limpar_cesta()
    usuario = usuario_atual()
    if usuario:
        registrar_auditoria(usuario.get("id"), "cesta_limpar", "cesta", "", {}, request.remote_addr)
    return _resposta_cesta()
