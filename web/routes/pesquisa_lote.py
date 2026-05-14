import logging
import time

from flask import Blueprint, current_app, render_template, request

from auth.decorators import login_required
from auth.session_manager import usuario_atual
from storage.app_storage import registrar_auditoria, salvar_pesquisa_usuario
from utils.util import converter_numero
from web.services.filtros_service import (
    filtrar_orgao_origem,
    filtrar_periodo_resultados,
    gerar_item_uid,
    periodo_para_datas,
    preparar_resultados,
)
from web.services.pesquisa_service import executar_pesquisa_item


logger = logging.getLogger(__name__)
pesquisa_lote_bp = Blueprint("pesquisa_lote", __name__, url_prefix="/pesquisa-lote")
MAX_ITENS_LOTE = 100
TOLERANCIA_PADRAO = 20
RESULTADOS_PADRAO = 8
MAX_RESULTADOS_POR_ITEM = 50


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
        elif len(partes) == 3:
            descricao, qtd_min_txt, qtd_max_txt = partes
        else:
            erros.append({
                "linha": numero_linha,
                "texto": original,
                "erro": "Use o formato: descricao | qtd_min | qtd_max.",
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
            "qtd_min": qtd_min,
            "qtd_max": qtd_max,
            "qtd_min_txt": qtd_min_txt,
            "qtd_max_txt": qtd_max_txt,
            "item_uid": gerar_item_uid(descricao, f"{qtd_min_txt}-{qtd_max_txt}"),
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
    total_linhas = max(len(numeros), len(descricoes), len(quantidades))

    for idx in range(total_linhas):
        numero = numeros[idx].strip() if idx < len(numeros) else ""
        descricao = descricoes[idx].strip() if idx < len(descricoes) else ""
        quantidade_txt = quantidades[idx].strip() if idx < len(quantidades) else ""

        if not numero and not descricao and not quantidade_txt:
            continue

        linha = idx + 1
        quantidade = converter_numero(quantidade_txt)
        if not descricao:
            erros.append({"linha": linha, "texto": quantidade_txt, "erro": "Descricao obrigatoria."})
            continue
        if quantidade is None or quantidade <= 0:
            erros.append({"linha": linha, "texto": descricao, "erro": "Quantidade obrigatoria e maior que zero."})
            continue

        qtd_min, qtd_max = calcular_faixa_quantidade(quantidade, tolerancia)
        itens.append({
            "linha": linha,
            "numero": numero or str(linha),
            "descricao": descricao,
            "quantidade": quantidade,
            "quantidade_txt": quantidade_txt,
            "tolerancia_percentual": tolerancia,
            "qtd_min": qtd_min,
            "qtd_max": qtd_max,
            "qtd_min_txt": _fmt_numero(qtd_min),
            "qtd_max_txt": _fmt_numero(qtd_max),
            "item_uid": gerar_item_uid(descricao, quantidade_txt),
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
            {"numero": "1", "descricao": "", "quantidade": ""},
        ],
        "tolerancia_percentual": TOLERANCIA_PADRAO,
        "quantidade_resultados": RESULTADOS_PADRAO,
        "desconsiderar_orgao_origem": "",
        "orgao_origem": "Prefeitura Municipal de Jóia",
        "periodo_pesquisa": "12m",
        "data_inicial": "",
        "data_final": "",
        "exemplo": exemplo,
        "resultados_lote": [],
        "erros": [],
        "resumo": None,
    }

    if request.method == "GET":
        return render_template("pesquisa_lote.html", **contexto)

    texto_lote = request.form.get("itens_lote", "")
    desconsiderar_orgao_origem = request.form.get("desconsiderar_orgao_origem") == "1"
    orgao_origem = request.form.get("orgao_origem", "Prefeitura Municipal de Jóia").strip()
    periodo_pesquisa = request.form.get("periodo_pesquisa", "12m")
    data_inicial_txt = request.form.get("data_inicial", "").strip()
    data_final_txt = request.form.get("data_final", "").strip()
    quantidade_resultados = _limite_resultados(request.form.get("quantidade_resultados", RESULTADOS_PADRAO))
    fontes = request.form.getlist("fontes") or ["licitacon"]
    contexto["desconsiderar_orgao_origem"] = "1" if desconsiderar_orgao_origem else ""
    contexto["orgao_origem"] = orgao_origem
    contexto["periodo_pesquisa"] = periodo_pesquisa
    contexto["data_inicial"] = data_inicial_txt
    contexto["data_final"] = data_final_txt
    contexto["quantidade_resultados"] = quantidade_resultados
    contexto["texto_lote"] = texto_lote
    if texto_lote.strip():
        itens, erros = parse_linhas_lote(texto_lote)
        contexto["linhas_planilha"] = []
    else:
        itens, erros, tolerancia, linhas_form = parse_planilha_lote(request.form)
        contexto["tolerancia_percentual"] = _fmt_numero(tolerancia)
        contexto["linhas_planilha"] = linhas_form
    contexto["erros"] = erros

    inicio_lote = time.perf_counter()
    resultados_lote = []

    for item in itens:
        inicio_item = time.perf_counter()
        try:
            criterios, resultados, estatisticas = executar_pesquisa_item(
                item["descricao"],
                item["qtd_min"],
                item["qtd_max"],
                limite=current_app.config["MAX_CANDIDATOS_FLASK"],
                search_db_mode=current_app.config["SEARCH_DB_MODE"],
                raw_path=current_app.config["LICITACON_SQLITE_PATH"],
                operational_path=current_app.config["SEARCH_DB_PATH"],
                fontes=fontes,
            )
            data_inicial, data_final = periodo_para_datas(periodo_pesquisa, data_inicial_txt, data_final_txt)
            resultados, removidos_periodo = filtrar_periodo_resultados(resultados, data_inicial, data_final)
            resultados, removidos_orgao = filtrar_orgao_origem(
                resultados,
                orgao_origem,
                desconsiderar_orgao_origem,
            )
            resultados = preparar_resultados(resultados, item["item_uid"])
            estatisticas["filtrados_orgao_origem"] = removidos_orgao
            estatisticas["filtrados_periodo"] = removidos_periodo
            estatisticas["total_exibido"] = len(resultados)
            tempo_item_ms = round((time.perf_counter() - inicio_item) * 1000, 2)
            resultados_lote.append({
                "item": item,
                "criterios": criterios,
                "resultados": resultados[:quantidade_resultados],
                "estatisticas": estatisticas,
                "tempo_item_ms": tempo_item_ms,
                "erro": "",
            })
            logger.info(
                "Lote linha=%s resultados=%s tempo_ms=%s sqlite=%s",
                item["linha"],
                len(resultados),
                tempo_item_ms,
                estatisticas.get("sqlite_search"),
            )
        except Exception as erro:
            tempo_item_ms = round((time.perf_counter() - inicio_item) * 1000, 2)
            resultados_lote.append({
                "item": item,
                "criterios": None,
                "resultados": [],
                "estatisticas": None,
                "tempo_item_ms": tempo_item_ms,
                "erro": str(erro),
            })
            logger.exception("Erro no lote linha=%s", item["linha"])

    total_ms = round((time.perf_counter() - inicio_lote) * 1000, 2)
    sucesso = sum(1 for bloco in resultados_lote if not bloco["erro"])
    contexto["resultados_lote"] = resultados_lote
    contexto["resumo"] = {
        "itens_validos": len(itens),
        "sucesso": sucesso,
        "erros": len(erros) + (len(resultados_lote) - sucesso),
        "tempo_total_ms": total_ms,
    }
    usuario = usuario_atual()
    if usuario:
        pesquisa_id = salvar_pesquisa_usuario(
            usuario.get("id"),
            "Pesquisa em lote",
            fontes,
            "lote",
            {"resumo": contexto["resumo"], "resultados_lote": resultados_lote},
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
