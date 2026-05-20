import logging
import statistics
import time

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from ia.ia_criterios import extrair_criterios_com_ia
from storage.app_storage import (
    criar_cotacao_operacional,
    obter_cotacao_operacional,
    registrar_auditoria,
    salvar_pesquisa_usuario,
    salvar_workspace_cotacao,
)
from utils.util import converter_numero
from web.services.filtros_service import (
    filtrar_orgao_origem,
    filtrar_periodo_resultados,
    gerar_item_uid,
    periodo_para_datas,
    preparar_resultados,
)
from web.services.pesquisa_service import executar_pesquisa_item
from web.services.lote_workspace_service import carregar_workspace, novo_workspace_id, salvar_workspace_local
from search.sources import normalizar_fontes
from search.units import UNIDADES_PADRAO, normalizar_unidade


logger = logging.getLogger(__name__)
pesquisa_lote_bp = Blueprint("pesquisa_lote", __name__, url_prefix="/pesquisa-lote")
MAX_ITENS_LOTE = 200
TOLERANCIA_PADRAO = 20
RESULTADOS_PADRAO = 8
MAX_RESULTADOS_POR_ITEM = 50
COTACAO_ATIVA_KEY = "cotacao_operacional_ativa_id"


def _workspace_vazio():
    return {"itens": [], "fontes": ["licitacon"], "config": {}, "criado_em": time.time()}


def obter_workspace():
    cotacao_id = session.get(COTACAO_ATIVA_KEY)
    if cotacao_id:
        usuario = usuario_atual() or {}
        cotacao = obter_cotacao_operacional(cotacao_id, usuario.get("id"))
        if cotacao:
            workspace = cotacao.get("workspace") or _workspace_vazio()
            workspace["cotacao_id"] = cotacao_id
            workspace["cotacao_nome"] = cotacao.get("nome") or cotacao.get("item_pesquisado")
            workspace["cotacao_status"] = cotacao.get("status")
            workspace.setdefault("itens", [])
            workspace.setdefault("fontes", ["licitacon"])
            workspace.setdefault("config", {})
            return workspace
    workspace = carregar_workspace(_workspace_vazio)
    workspace.setdefault("itens", [])
    workspace.setdefault("fontes", ["licitacon"])
    workspace.setdefault("config", {})
    return workspace


def salvar_workspace(workspace):
    salvar_workspace_local(workspace)
    cotacao_id = workspace.get("cotacao_id") or session.get(COTACAO_ATIVA_KEY)
    if cotacao_id:
        usuario = usuario_atual() or {}
        salvar_workspace_cotacao(
            cotacao_id,
            workspace,
            workspace.get("item_atual_uid", ""),
            usuario.get("id"),
        )


def _definir_cotacao_ativa(cotacao_id):
    usuario = usuario_atual() or {}
    cotacao = obter_cotacao_operacional(cotacao_id, usuario.get("id"))
    if not cotacao:
        return None
    session[COTACAO_ATIVA_KEY] = int(cotacao_id)
    session.modified = True
    return cotacao


def _termos_csv(valor):
    if isinstance(valor, str):
        return [parte.strip() for parte in valor.split(",") if parte.strip()]
    return [str(parte).strip() for parte in (valor or []) if str(parte).strip()]


def _texto_termos(valor):
    return ", ".join(_termos_csv(valor))


def _item_por_uid(workspace, item_uid):
    for item in workspace.get("itens", []):
        if item.get("item_uid") == item_uid:
            return item
    return None


def _vizinhos_item(workspace, item_uid):
    itens = workspace.get("itens", [])
    uids = [item.get("item_uid") for item in itens]
    if item_uid not in uids:
        return None, None
    indice = uids.index(item_uid)
    anterior = itens[indice - 1] if indice > 0 else None
    proximo = itens[indice + 1] if indice + 1 < len(itens) else None
    return anterior, proximo


def _valor_resultado(resultado):
    return converter_numero(resultado.get("valor_unitario") or resultado.get("valor"))


def _indicadores_amostra_item(item):
    resultados = list((item or {}).get("resultados") or [])
    valores = [valor for valor in (_valor_resultado(r) for r in resultados) if valor and valor > 0]
    scores = [
        float(score)
        for score in (converter_numero(r.get("score")) for r in resultados)
        if score is not None
    ]
    validos = [
        r for r in resultados
        if (r.get("status_validacao") or "VALIDO") == "VALIDO"
        and not r.get("motivos_alerta")
    ]
    suspeitos = [
        r for r in resultados
        if (r.get("status_validacao") or "VALIDO") != "VALIDO"
        or bool(r.get("motivos_alerta"))
    ]
    baixa_equivalencia = [
        r for r in resultados
        if (converter_numero(r.get("score_quantidade")) or 100) < 45
    ]
    media = statistics.mean(valores) if valores else 0
    dispersao = (statistics.pstdev(valores) / media * 100) if len(valores) > 1 and media else 0
    score_medio = statistics.mean(scores) if scores else 0

    chips = []
    if len(validos) >= 3 and dispersao <= 30 and not suspeitos and score_medio >= 65:
        chips.append({"tipo": "ok", "texto": "Preco valido"})
    if suspeitos or baixa_equivalencia or (scores and score_medio < 60):
        chips.append({"tipo": "warn", "texto": "Preco suspeito"})
    if dispersao > 30:
        chips.append({"tipo": "warn", "texto": "Alta dispersao"})
    if len(validos) < 3:
        chips.append({"tipo": "muted", "texto": "Amostra fraca"})
    if not chips:
        chips.append({"tipo": "muted", "texto": "Aguardando validacao"})

    return {
        "chips": chips,
        "score_medio": round(score_medio, 2) if scores else None,
        "validos": len(validos),
        "suspeitos": len(suspeitos),
        "dispersao_percentual": round(dispersao, 2) if valores else None,
        "total": len(resultados),
    }


def _enriquecer_item_importado(item):
    criterios = extrair_criterios_com_ia(item["descricao"])
    semantic_core = (
        criterios.get("semantic_core")
        or criterios.get("descricao_sugerida_licitacon")
        or criterios.get("descricao_resumida")
        or item["descricao"]
    )
    return {
        **item,
        "descricao_original": item["descricao"],
        "descricao_ia": criterios.get("descricao_resumida") or item["descricao"],
        "semantic_core": semantic_core,
        "termos_obrigatorios": _termos_csv(criterios.get("termos_obrigatorios")),
        "termos_importantes": _termos_csv(criterios.get("termos_importantes")),
        "termos_excluir": _termos_csv(criterios.get("termos_excluir") or criterios.get("termos_proibidos")),
        "criterios_ia": criterios,
        "status_operacional": "nao_pesquisado",
        "historico": [],
        "resultados": [],
        "estatisticas": None,
        "erro": "",
    }


def _aplicar_edicao_item(item, form):
    item["descricao_ia"] = form.get("descricao_ia", item.get("descricao_ia", "")).strip()
    item["semantic_core"] = form.get("semantic_core", item.get("semantic_core", "")).strip()
    item["termos_obrigatorios"] = _termos_csv(form.get("termos_obrigatorios", _texto_termos(item.get("termos_obrigatorios"))))
    item["termos_importantes"] = _termos_csv(form.get("termos_importantes", _texto_termos(item.get("termos_importantes"))))
    item["termos_excluir"] = _termos_csv(form.get("termos_excluir", _texto_termos(item.get("termos_excluir"))))
    item["status_operacional"] = form.get("status_operacional", item.get("status_operacional", "em_analise"))
    quantidade = converter_numero(form.get("quantidade_item", item.get("quantidade", 0)))
    if quantidade is not None:
        item["quantidade"] = quantidade
        item["quantidade_txt"] = _fmt_numero(quantidade)
    item["unidade"] = normalizar_unidade(form.get("unidade_item", item.get("unidade", "UN")))
    tolerancia = converter_numero(form.get("tolerancia_percentual", item.get("tolerancia_percentual", TOLERANCIA_PADRAO)))
    if tolerancia is None or tolerancia < 0 or tolerancia > 100:
        tolerancia = item.get("tolerancia_percentual", TOLERANCIA_PADRAO)
    item["tolerancia_percentual"] = tolerancia
    if (item.get("quantidade") or 0) > 0:
        qtd_min, qtd_max = calcular_faixa_quantidade(float(item["quantidade"]), float(tolerancia))
    else:
        qtd_min, qtd_max = 1, 999999
    item["qtd_min"] = qtd_min
    item["qtd_max"] = qtd_max
    item["qtd_min_txt"] = _fmt_numero(qtd_min)
    item["qtd_max_txt"] = _fmt_numero(qtd_max)


def _criterios_manual(item):
    criterios = dict(item.get("criterios_ia") or {})
    criterios.update({
        "descricao_resumida": item.get("descricao_ia") or item.get("descricao_original"),
        "descricao_sugerida_licitacon": item.get("semantic_core") or item.get("descricao_original"),
        "semantic_core": item.get("semantic_core") or item.get("descricao_original"),
        "termos_obrigatorios": list(item.get("termos_obrigatorios") or []),
        "termos_importantes": list(item.get("termos_importantes") or []),
        "termos_excluir": list(item.get("termos_excluir") or []),
    })
    return criterios


def parse_linhas_lote(texto):
    itens = []
    erros = []

    for numero_linha, linha in enumerate(str(texto or "").splitlines(), start=1):
        original = linha
        linha = linha.strip()
        if not linha:
            continue

        partes = [parte.strip() for parte in linha.split("|")]
        if len(partes) == 1:
            descricao = partes[0]
            qtd_min_txt = "1"
            qtd_max_txt = "999999"
            unidade = "UN"
        elif len(partes) == 3:
            descricao, qtd_min_txt, qtd_max_txt = partes
            unidade = "UN"
        elif len(partes) == 4:
            descricao, qtd_min_txt, qtd_max_txt, unidade = partes
        else:
            erros.append({
                "linha": numero_linha,
                "texto": original,
                "erro": "Use o formato: descricao | qtd_min | qtd_max | unidade.",
            })
            continue

        qtd_min = converter_numero(qtd_min_txt)
        qtd_max = converter_numero(qtd_max_txt)
        if not descricao:
            erros.append({"linha": numero_linha, "texto": original, "erro": "Descricao vazia."})
            continue
        if qtd_min is None or qtd_max is None:
            erros.append({"linha": numero_linha, "texto": original, "erro": "Quantidade invalida."})
            continue
        if qtd_min > qtd_max:
            erros.append({
                "linha": numero_linha,
                "texto": original,
                "erro": "Quantidade minima maior que a maxima.",
            })
            continue

        itens.append({
            "linha": numero_linha,
            "numero": str(numero_linha),
            "descricao": descricao,
            "quantidade": "",
            "quantidade_txt": "",
            "unidade": normalizar_unidade(unidade),
            "qtd_min": qtd_min,
            "qtd_max": qtd_max,
            "qtd_min_txt": qtd_min_txt,
            "qtd_max_txt": qtd_max_txt,
            "item_uid": gerar_item_uid(descricao, f"{qtd_min_txt}-{qtd_max_txt}-{normalizar_unidade(unidade)}"),
        })

    if len(itens) > MAX_ITENS_LOTE:
        for item in itens[MAX_ITENS_LOTE:]:
            erros.append({
                "linha": item["linha"],
                "texto": item["descricao"],
                "erro": f"Limite inicial de {MAX_ITENS_LOTE} itens por lote.",
            })
        itens = itens[:MAX_ITENS_LOTE]

    return itens, erros


def calcular_faixa_quantidade(quantidade, tolerancia_percentual):
    fator = tolerancia_percentual / 100
    qtd_min = quantidade * (1 - fator)
    qtd_max = quantidade * (1 + fator)
    return max(0, qtd_min), qtd_max


def _fmt_numero(valor):
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    return texto or "0"


def _limite_resultados(valor):
    numero = converter_numero(valor)
    if numero is None:
        return RESULTADOS_PADRAO
    return max(1, min(int(numero), MAX_RESULTADOS_POR_ITEM))


def parse_planilha_lote(form):
    itens = []
    erros = []

    tolerancia_txt = str(form.get("tolerancia_percentual", TOLERANCIA_PADRAO)).strip()
    tolerancia = converter_numero(tolerancia_txt)
    if tolerancia is None or tolerancia < 0 or tolerancia > 100:
        tolerancia = TOLERANCIA_PADRAO
        erros.append({
            "linha": "-",
            "texto": tolerancia_txt,
            "erro": f"Percentual invalido. Usando {TOLERANCIA_PADRAO}%.",
        })

    numeros = form.getlist("item_numero[]")
    descricoes = form.getlist("descricao[]")
    quantidades = form.getlist("quantidade[]")
    unidades = form.getlist("unidade[]")
    total_linhas = max(len(numeros), len(descricoes), len(quantidades), len(unidades))

    for idx in range(total_linhas):
        numero = numeros[idx].strip() if idx < len(numeros) else ""
        descricao = descricoes[idx].strip() if idx < len(descricoes) else ""
        quantidade_txt = quantidades[idx].strip() if idx < len(quantidades) else ""
        unidade_raw = unidades[idx].strip() if idx < len(unidades) else ""
        unidade = normalizar_unidade(unidade_raw or "UN")

        if not descricao and not quantidade_txt and not unidade_raw:
            continue

        linha = idx + 1
        if not descricao:
            erros.append({"linha": linha, "texto": quantidade_txt, "erro": "Descricao obrigatoria."})
            continue
        quantidade = converter_numero(quantidade_txt) if quantidade_txt else 0
        if quantidade is None:
            erros.append({"linha": linha, "texto": descricao, "erro": "Quantidade invalida."})
            continue

        if quantidade > 0:
            qtd_min, qtd_max = calcular_faixa_quantidade(quantidade, tolerancia)
            quantidade_txt_item = quantidade_txt
        else:
            qtd_min, qtd_max = 1, 999999
            quantidade_txt_item = "0"
        itens.append({
            "linha": linha,
            "numero": numero or str(linha),
            "descricao": descricao,
            "quantidade": quantidade,
            "quantidade_txt": quantidade_txt_item,
            "unidade": unidade,
            "tolerancia_percentual": tolerancia,
            "qtd_min": qtd_min,
            "qtd_max": qtd_max,
            "qtd_min_txt": _fmt_numero(qtd_min),
            "qtd_max_txt": _fmt_numero(qtd_max),
            "item_uid": gerar_item_uid(descricao, f"{quantidade_txt_item}-{unidade}"),
            "entrada": "planilha",
        })

    if len(itens) > MAX_ITENS_LOTE:
        for item in itens[MAX_ITENS_LOTE:]:
            erros.append({
                "linha": item["linha"],
                "texto": item["descricao"],
                "erro": f"Limite inicial de {MAX_ITENS_LOTE} itens por lote.",
            })
        itens = itens[:MAX_ITENS_LOTE]

    linhas_form = []
    for idx in range(max(total_linhas, 1)):
        linhas_form.append({
            "numero": numeros[idx].strip() if idx < len(numeros) else str(idx + 1),
            "descricao": descricoes[idx].strip() if idx < len(descricoes) else "",
            "quantidade": quantidades[idx].strip() if idx < len(quantidades) else "",
            "unidade": normalizar_unidade(unidades[idx] if idx < len(unidades) else "UN"),
        })

    return itens, erros, tolerancia, linhas_form


@pesquisa_lote_bp.route("", methods=["GET", "POST"])
@pesquisa_lote_bp.route("/", methods=["GET", "POST"])
@login_required
def pesquisa_lote():
    exemplo = (
        "rele falta fase 380v | 1 | 20\n"
        "notebook intel i5 8gb ssd | 5 | 20\n"
        "pneu 275/80r22.5 radial misto | 10 | 50\n"
        "oleo 15w40 diesel | 20 | 200"
    )
    contexto = {
        "app_name": current_app.config["APP_NAME"],
        "status": "Busca em lote",
        "texto_lote": "",
        "linhas_planilha": [
            {"numero": "1", "descricao": "", "quantidade": "", "unidade": "UN"},
        ],
        "unidades_padrao": UNIDADES_PADRAO,
        "tolerancia_percentual": TOLERANCIA_PADRAO,
        "quantidade_resultados": RESULTADOS_PADRAO,
        "desconsiderar_orgao_origem": "",
        "orgao_origem": "Prefeitura Municipal de Jóia",
        "periodo_pesquisa": "12m",
        "fontes": ["licitacon"],
        "data_inicial": "",
        "data_final": "",
        "exemplo": exemplo,
        "resultados_lote": [],
        "workspace": obter_workspace(),
        "selected_item": None,
        "prev_item": None,
        "next_item": None,
        "item_indicators": None,
        "erros": [],
        "resumo": None,
    }

    cotacao_id_param = request.args.get("cotacao_id")
    if cotacao_id_param:
        _definir_cotacao_ativa(cotacao_id_param)

    if request.method == "GET":
        item_uid = request.args.get("item")
        contexto["workspace"] = obter_workspace()
        contexto["fontes"] = contexto["workspace"].get("fontes", contexto["fontes"])
        contexto["quantidade_resultados"] = contexto["workspace"].get("config", {}).get("quantidade_resultados", contexto["quantidade_resultados"])
        contexto["selected_item"] = _item_por_uid(contexto["workspace"], item_uid) if item_uid else None
        if not contexto["selected_item"] and contexto["workspace"].get("itens"):
            contexto["selected_item"] = contexto["workspace"]["itens"][0]
        if contexto["selected_item"]:
            contexto["workspace"]["item_atual_uid"] = contexto["selected_item"]["item_uid"]
            contexto["prev_item"], contexto["next_item"] = _vizinhos_item(
                contexto["workspace"],
                contexto["selected_item"]["item_uid"],
            )
            contexto["item_indicators"] = _indicadores_amostra_item(contexto["selected_item"])
            salvar_workspace(contexto["workspace"])
        return render_template("pesquisa_lote.html", **contexto)

    texto_lote = request.form.get("itens_lote", "")
    desconsiderar_orgao_origem = request.form.get("desconsiderar_orgao_origem") == "1"
    orgao_origem = request.form.get("orgao_origem", "Prefeitura Municipal de Jóia").strip()
    periodo_pesquisa = request.form.get("periodo_pesquisa", "12m")
    data_inicial_txt = request.form.get("data_inicial", "").strip()
    data_final_txt = request.form.get("data_final", "").strip()
    quantidade_resultados = _limite_resultados(request.form.get("quantidade_resultados", RESULTADOS_PADRAO))
    fontes = normalizar_fontes(request.form.getlist("fontes") or ["licitacon"])
    contexto["desconsiderar_orgao_origem"] = "1" if desconsiderar_orgao_origem else ""
    contexto["orgao_origem"] = orgao_origem
    contexto["periodo_pesquisa"] = periodo_pesquisa
    contexto["data_inicial"] = data_inicial_txt
    contexto["data_final"] = data_final_txt
    contexto["quantidade_resultados"] = quantidade_resultados
    contexto["texto_lote"] = texto_lote
    contexto["fontes"] = fontes
    if texto_lote.strip():
        itens, erros = parse_linhas_lote(texto_lote)
        contexto["linhas_planilha"] = []
        contexto["unidades_padrao"] = UNIDADES_PADRAO
    else:
        itens, erros, tolerancia, linhas_form = parse_planilha_lote(request.form)
        contexto["tolerancia_percentual"] = _fmt_numero(tolerancia)
        contexto["linhas_planilha"] = linhas_form
    contexto["erros"] = erros

    inicio_lote = time.perf_counter()
    itens_importados = [_enriquecer_item_importado(item) for item in itens]
    total_ms = round((time.perf_counter() - inicio_lote) * 1000, 2)
    usuario = usuario_atual()
    cotacao_id = session.get(COTACAO_ATIVA_KEY)
    if not cotacao_id:
        nome_cotacao = request.form.get("nome_cotacao", "").strip() or f"Cotacao {time.strftime('%d/%m/%Y %H:%M')}"
        cotacao_id = criar_cotacao_operacional(nome_cotacao, "", usuario.get("id") if usuario else None)
        session[COTACAO_ATIVA_KEY] = int(cotacao_id)
        session.modified = True
    novo_workspace_id()
    workspace = {
        "itens": itens_importados,
        "fontes": fontes,
        "cotacao_id": cotacao_id,
        "cotacao_nome": (obter_cotacao_operacional(cotacao_id, usuario.get("id") if usuario else None) or {}).get("nome"),
        "config": {
            "periodo_pesquisa": periodo_pesquisa,
            "data_inicial": data_inicial_txt,
            "data_final": data_final_txt,
            "desconsiderar_orgao_origem": desconsiderar_orgao_origem,
            "orgao_origem": orgao_origem,
            "quantidade_resultados": quantidade_resultados,
        },
        "criado_em": time.time(),
    }
    salvar_workspace(workspace)
    contexto["workspace"] = workspace
    contexto["selected_item"] = itens_importados[0] if itens_importados else None
    if contexto["selected_item"]:
        workspace["item_atual_uid"] = contexto["selected_item"]["item_uid"]
        contexto["prev_item"], contexto["next_item"] = _vizinhos_item(
            workspace,
            contexto["selected_item"]["item_uid"],
        )
        contexto["item_indicators"] = _indicadores_amostra_item(contexto["selected_item"])
    salvar_workspace(workspace)
    contexto["resumo"] = {
        "itens_validos": len(itens),
        "sucesso": len(itens_importados),
        "erros": len(erros),
        "tempo_total_ms": total_ms,
    }
    if usuario:
        pesquisa_id = salvar_pesquisa_usuario(
            usuario.get("id"),
            "Importacao de lote",
            fontes,
            "lote_importado",
            {"resumo": contexto["resumo"], "itens": itens_importados},
        )
        registrar_auditoria(
            usuario.get("id"),
            "pesquisa_lote",
            "pesquisas",
            pesquisa_id,
            {"itens": len(itens), "fontes": fontes},
            request.remote_addr,
        )
        contexto["pesquisa_id"] = pesquisa_id
    return render_template("pesquisa_lote.html", **contexto)


@pesquisa_lote_bp.post("/item/<item_uid>/pesquisar")
@login_required
def pesquisar_item_workspace(item_uid):
    workspace = obter_workspace()
    item = _item_por_uid(workspace, item_uid)
    if not item:
        return redirect(url_for("pesquisa_lote.pesquisa_lote"))

    _aplicar_edicao_item(item, request.form)
    config = workspace.get("config", {})
    fontes = normalizar_fontes(request.form.getlist("fontes") or workspace.get("fontes") or ["licitacon"])
    workspace["fontes"] = fontes
    workspace["item_atual_uid"] = item_uid
    config["periodo_pesquisa"] = request.form.get("periodo_pesquisa", config.get("periodo_pesquisa", "12m"))
    config["data_inicial"] = request.form.get("data_inicial", config.get("data_inicial", "")).strip()
    config["data_final"] = request.form.get("data_final", config.get("data_final", "")).strip()
    config["orgao_origem"] = request.form.get("orgao_origem", config.get("orgao_origem", "Prefeitura Municipal de Joia")).strip()
    config["desconsiderar_orgao_origem"] = request.form.get("desconsiderar_orgao_origem") == "1"
    workspace["config"] = config
    estrategia_busca = request.form.get("estrategia_busca", item.get("estrategia_busca", "inteligente"))
    if estrategia_busca not in {"inteligente", "rigida", "ampla"}:
        estrategia_busca = "inteligente"
    item["estrategia_busca"] = estrategia_busca
    quantidade_resultados = _limite_resultados(request.form.get("quantidade_resultados", config.get("quantidade_resultados", RESULTADOS_PADRAO)))
    descricao_busca = item.get("semantic_core") or item.get("descricao_ia") or item.get("descricao_original")
    criterios_manual = _criterios_manual(item)
    inicio_item = time.perf_counter()
    try:
        criterios, resultados, estatisticas = executar_pesquisa_item(
            descricao_busca,
            item["qtd_min"],
            item["qtd_max"],
            limite=current_app.config["MAX_CANDIDATOS_FLASK"],
            search_db_mode=current_app.config["SEARCH_DB_MODE"],
            raw_path=current_app.config["LICITACON_SQLITE_PATH"],
            operational_path=current_app.config["SEARCH_DB_PATH"],
            fontes=fontes,
            criterios_override=criterios_manual,
            estrategia_busca=estrategia_busca,
        )
        criterios.update(criterios_manual)
        data_inicial, data_final = periodo_para_datas(
            config.get("periodo_pesquisa", "12m"),
            config.get("data_inicial", ""),
            config.get("data_final", ""),
        )
        resultados, removidos_periodo = filtrar_periodo_resultados(resultados, data_inicial, data_final)
        resultados, removidos_orgao = filtrar_orgao_origem(
            resultados,
            config.get("orgao_origem", "Prefeitura Municipal de Joia"),
            bool(config.get("desconsiderar_orgao_origem")),
        )
        resultados = preparar_resultados(resultados, item["item_uid"])
        estatisticas["filtrados_orgao_origem"] = removidos_orgao
        estatisticas["filtrados_periodo"] = removidos_periodo
        estatisticas["total_exibido"] = len(resultados)
        tempo_item_ms = round((time.perf_counter() - inicio_item) * 1000, 2)
        pesquisa = {
            "descricao_busca": descricao_busca,
            "fontes": fontes,
            "estrategia_busca": estrategia_busca,
            "criterios": criterios,
            "estatisticas": estatisticas,
            "resultados": resultados[:quantidade_resultados],
            "tempo_item_ms": tempo_item_ms,
            "criado_em": time.time(),
        }
        item.setdefault("historico", []).append(pesquisa)
        acumulados = item.setdefault("resultados", [])
        existentes = {r.get("resultado_uid") for r in acumulados}
        for resultado in resultados[:quantidade_resultados]:
            if resultado.get("resultado_uid") not in existentes:
                acumulados.append(resultado)
                existentes.add(resultado.get("resultado_uid"))
        item["estatisticas"] = estatisticas
        item["status_operacional"] = "em_analise" if resultados else "revisar"
        item["erro"] = ""
        score_stats = ((estatisticas.get("providers") or {}).get("licitacon") or {}).get("score_stats", {})
        logger.info(
            "[item_summary] item=%s descricao=%r candidatos=%s descartados=%s score_pesado=%s resultados_finais=%s tempo_ms=%s",
            item["linha"],
            descricao_busca,
            score_stats.get("candidatos", estatisticas.get("candidatos", 0)),
            score_stats.get("descartados", 0),
            score_stats.get("score_pesado", 0),
            len(resultados),
            tempo_item_ms,
        )
    except Exception as erro:
        item["erro"] = str(erro)
        item["status_operacional"] = "revisar"
        logger.exception("Erro na pesquisa individual do lote item=%s", item_uid)
    salvar_workspace(workspace)
    return redirect(url_for("pesquisa_lote.pesquisa_lote", item=item_uid))


@pesquisa_lote_bp.post("/item/<item_uid>/status")
@login_required
def atualizar_status_item(item_uid):
    workspace = obter_workspace()
    item = _item_por_uid(workspace, item_uid)
    if item:
        status = request.form.get("status_operacional", item.get("status_operacional", "em_analise"))
        if status in {"nao_pesquisado", "em_analise", "validado", "revisar"}:
            item["status_operacional"] = status
            salvar_workspace(workspace)
    return redirect(url_for("pesquisa_lote.pesquisa_lote", item=item_uid))
