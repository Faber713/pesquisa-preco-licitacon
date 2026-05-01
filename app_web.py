import os
import re
import sqlite3
import tempfile
import json
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from datetime import datetime
from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config import MIN_RESULTADOS_DESEJADOS, LINK_BASE_LICITACON
from util import converter_numero, normalizar, palavras_fortes
from ia_criterios import extrair_criterios_com_ia
from busca import buscar_item, juntar_resultados
from html_saida import salvar_html
from normativos import (
    avaliar_conformidade_pesquisa,
    extrair_texto_normativo,
    formatar_moeda,
    inferir_perfil_decreto,
    listar_perfis_normativos,
    obter_perfil_normativo,
    perfil_de_dict,
    perfil_para_dict,
    registrar_perfil_normativo,
)
from app_storage import (
    cadastrar_cotacao,
    cadastrar_fornecedor,
    inicializar_app_db,
    listar_fornecedores,
    salvar_pesquisa,
)
from fontes_preco import (
    fonte_para_resultado,
    fontes_para_dataframe_linhas,
    resultado_licitacon_para_fonte,
)
from provedores_precos import buscar_fornecedores, buscar_pncp, buscar_web


CAMINHO_SQLITE = Path("licitacon.sqlite")
MAX_CANDIDATOS_SQLITE = 15000
MAX_CANDIDATOS_LOTE = 5000
TABELAS_SQLITE_BUSCA = {
    "base_pesquisa": {
        "rotulo": "LicitaCon geral",
        "campos_extras": "'' AS \"Municipio Fonte\", '' AS \"Grupo Regional\", 'LicitaCon geral' AS \"Fonte Base\"",
    },
    "base_historica_municipios": {
        "rotulo": "Historico regional",
        "campos_extras": "municipio AS \"Municipio Fonte\", grupo_regional AS \"Grupo Regional\", 'Historico regional' AS \"Fonte Base\"",
    },
}

inicializar_app_db()

if "perfil_normativo_upload" in st.session_state:
    registrar_perfil_normativo(perfil_de_dict(st.session_state["perfil_normativo_upload"]))


# ============================================================
# INTERFACE WEB - PESQUISA INTELIGENTE LICITACON
# ============================================================
# Este arquivo NAO substitui o busca_interativa.py.
# Ele apenas cria uma interface web amigavel usando os mesmos modulos.
#
# Para executar:
#   streamlit run app_web.py
# ============================================================


st.set_page_config(
    page_title="Pesquisa Inteligente LicitaCon",
    page_icon=":mag:",
    layout="wide"
)


def carregar_csv(arquivo_enviado):
    if arquivo_enviado is None:
        return None

    bytes_arquivo = arquivo_enviado.getvalue()

    try:
        return pd.read_csv(
            pd.io.common.BytesIO(bytes_arquivo),
            sep=";",
            encoding="utf-8",
            dtype=str
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            pd.io.common.BytesIO(bytes_arquivo),
            sep=";",
            encoding="latin1",
            dtype=str
        )


def base_sqlite_disponivel():
    if not CAMINHO_SQLITE.exists():
        return False, "Arquivo licitacon.sqlite nao encontrado."

    try:
        with sqlite3.connect(CAMINHO_SQLITE) as con:
            con.execute("SELECT 1 FROM base_pesquisa LIMIT 1").fetchone()
        return True, ""
    except Exception as erro:
        return False, f"Nao foi possivel abrir a base SQLite: {erro}"


def tabela_sqlite_existe(nome_tabela):
    if not CAMINHO_SQLITE.exists():
        return False

    with sqlite3.connect(CAMINHO_SQLITE) as con:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (nome_tabela,)
        ).fetchone() is not None


def montar_termos_sqlite(descricao_busca, criterios):
    textos = [
        descricao_busca,
        criterios.get("descricao_sugerida_licitacon", ""),
        criterios.get("descricao_resumida", ""),
        " ".join(criterios.get("termos_obrigatorios", [])),
        " ".join(criterios.get("termos_importantes", [])),
    ]

    termos = []

    for texto in textos:
        termos.extend(palavras_fortes(texto))
        termos.extend(
            p.lower()
            for p in re.findall(r"\w{4,}", str(texto), flags=re.UNICODE)
        )

    termos = [
        termo for termo in dict.fromkeys(termos)
        if termo not in {"110", "220", "380", "volts", "bivolt", "horas"}
    ]

    return termos[:10]


def carregar_candidatos_sqlite(
    descricao_busca,
    criterios,
    limite=MAX_CANDIDATOS_SQLITE,
    tabela="base_pesquisa"
):
    if tabela not in TABELAS_SQLITE_BUSCA:
        raise ValueError(f"Tabela de busca nao permitida: {tabela}")

    if not tabela_sqlite_existe(tabela):
        return pd.DataFrame()

    termos = montar_termos_sqlite(descricao_busca, criterios)

    if not termos:
        raise ValueError("Nao foi possivel montar termos de busca para a base local.")

    condicoes = []
    parametros_filtro = []
    parametros_relevancia = []
    pontuacoes = []

    for termo in termos:
        condicoes.append("item LIKE ?")
        parametros_filtro.append(f"%{termo}%")
        pontuacoes.append("CASE WHEN item LIKE ? THEN 1 ELSE 0 END")
        parametros_relevancia.append(f"%{termo}%")

    expressao_relevancia = " + ".join(pontuacoes) or "0"
    parametros = parametros_filtro + parametros_relevancia + [limite]

    campos_extras = TABELAS_SQLITE_BUSCA[tabela]["campos_extras"]

    sql = f"""
        SELECT
            linha_csv AS "Linha CSV",
            item AS "Item",
            qtd AS "Qtd.",
            unidade AS "Un.",
            valor_unitario AS "Vl. Un. Homolog.",
            valor_total AS "Vl. Total Homolog.",
            orgao AS "Orgao",
            modalidade AS "Modalidade",
            nr AS "Nr.",
            ano AS "Ano",
            objeto AS "Objeto",
            abertura AS "Abertura",
            data_homologacao AS "Data Homologacao",
            vencedor AS "Vencedor",
            cpf_cnpj AS "CPF/CNPJ",
            link_licitacon AS "Link LicitaCon",
            {campos_extras},
            ({expressao_relevancia}) AS "_relevancia"
        FROM {tabela}
        WHERE ({' OR '.join(condicoes)})
          AND item IS NOT NULL
          AND TRIM(item) <> ''
          AND valor_unitario IS NOT NULL
          AND TRIM(valor_unitario) NOT IN ('', '0', '0.00')
          AND CAST(REPLACE(valor_unitario, ',', '.') AS REAL) > 0
          AND vencedor IS NOT NULL
          AND TRIM(vencedor) NOT IN ('', '-', '--', 'nan', 'None', 'NULL')
        ORDER BY
            _relevancia DESC,
            CASE
                WHEN valor_unitario IS NOT NULL AND TRIM(valor_unitario) NOT IN ('', '0', '0.00') THEN 0
                ELSE 1
            END,
            ano DESC
        LIMIT ?
    """

    with sqlite3.connect(CAMINHO_SQLITE) as con:
        return pd.read_sql_query(sql, con, params=parametros, dtype=str)


def executar_pesquisa(
    df,
    descricao_busca,
    qtd_min,
    qtd_max,
    criterios=None,
    permitir_complementar_sem_qtd=True,
    exigir_homologacao=True
):
    if criterios is None:
        criterios = extrair_criterios_com_ia(descricao_busca)

    resultados_rigido = buscar_item(
        df=df,
        descricao_busca=descricao_busca,
        qtd_min=qtd_min,
        qtd_max=qtd_max,
        criterios=criterios,
        modo="rigido",
        exigir_homologacao=exigir_homologacao
    )

    resultados_relaxado = buscar_item(
        df=df,
        descricao_busca=descricao_busca,
        qtd_min=qtd_min,
        qtd_max=qtd_max,
        criterios=criterios,
        modo="relaxado",
        exigir_homologacao=exigir_homologacao
    )

    resultados_amplo = buscar_item(
        df=df,
        descricao_busca=descricao_busca,
        qtd_min=qtd_min,
        qtd_max=qtd_max,
        criterios=criterios,
        modo="amplo",
        exigir_homologacao=exigir_homologacao
    )

    resultados_temp = juntar_resultados(
        resultados_rigido,
        resultados_relaxado,
        resultados_amplo
    )

    resultados_relaxado_sem_qtd = []
    resultados_amplo_sem_qtd = []

    if permitir_complementar_sem_qtd and len(resultados_temp) < MIN_RESULTADOS_DESEJADOS:
        resultados_relaxado_sem_qtd = buscar_item(
            df=df,
            descricao_busca=descricao_busca,
            qtd_min=qtd_min,
            qtd_max=qtd_max,
            criterios=criterios,
            modo="relaxado",
            ignorar_quantidade=True,
            exigir_homologacao=exigir_homologacao
        )

        resultados_amplo_sem_qtd = buscar_item(
            df=df,
            descricao_busca=descricao_busca,
            qtd_min=qtd_min,
            qtd_max=qtd_max,
            criterios=criterios,
            modo="amplo",
            ignorar_quantidade=True,
            exigir_homologacao=exigir_homologacao
        )

        resultados = juntar_resultados(
            resultados_rigido,
            resultados_relaxado,
            resultados_amplo,
            resultados_relaxado_sem_qtd,
            resultados_amplo_sem_qtd
        )
    else:
        resultados = resultados_temp

    estatisticas = {
        "linhas_csv": len(df),
        "total_resultados": len(resultados),
        "rigido": len(resultados_rigido),
        "relaxado": len(resultados_relaxado),
        "amplo": len(resultados_amplo),
        "relaxado_sem_qtd": len(resultados_relaxado_sem_qtd),
        "amplo_sem_qtd": len(resultados_amplo_sem_qtd),
        "total": len(resultados),
        "usou_criterios_ampliados": bool(resultados_amplo or resultados_amplo_sem_qtd or resultados_relaxado_sem_qtd)
    }

    return criterios, resultados, estatisticas


def executar_pesquisa_sqlite(descricao_busca, qtd_min, qtd_max, limite_candidatos=MAX_CANDIDATOS_SQLITE):
    criterios = extrair_criterios_com_ia(descricao_busca)
    df = carregar_candidatos_sqlite(
        descricao_busca,
        criterios,
        limite=limite_candidatos,
        tabela="base_pesquisa"
    )
    criterios, resultados, estatisticas = executar_pesquisa(
        df=df,
        descricao_busca=descricao_busca,
        qtd_min=qtd_min,
        qtd_max=qtd_max,
        criterios=criterios,
        permitir_complementar_sem_qtd=False,
        exigir_homologacao=True
    )

    candidatos_regionais = 0
    resultados_regionais = []

    if len(resultados) < MIN_RESULTADOS_DESEJADOS:
        df_regional = carregar_candidatos_sqlite(
            descricao_busca,
            criterios,
            limite=limite_candidatos,
            tabela="base_historica_municipios"
        )
        candidatos_regionais = len(df_regional)

        if not df_regional.empty:
            _criterios, resultados_regionais, estatisticas_regionais = executar_pesquisa(
                df=df_regional,
                descricao_busca=descricao_busca,
                qtd_min=qtd_min,
                qtd_max=qtd_max,
                criterios=criterios,
                permitir_complementar_sem_qtd=False,
                exigir_homologacao=True
            )
            resultados = juntar_resultados(resultados, resultados_regionais)
            estatisticas["regional_rigido"] = estatisticas_regionais.get("rigido", 0)
            estatisticas["regional_relaxado"] = estatisticas_regionais.get("relaxado", 0)
            estatisticas["regional_amplo"] = estatisticas_regionais.get("amplo", 0)

    estatisticas["fonte_dados"] = "Base LicitaCon local"
    estatisticas["candidatos_sqlite"] = len(df)
    estatisticas["candidatos_regionais"] = candidatos_regionais
    estatisticas["resultados_regionais"] = len(resultados_regionais)
    estatisticas["total_resultados"] = len(resultados)
    estatisticas["total"] = len(resultados)
    return criterios, resultados, estatisticas


def localizar_coluna(df, candidatos):
    mapa = {normalizar(coluna): coluna for coluna in df.columns}

    for candidato in candidatos:
        candidato_norm = normalizar(candidato)
        if candidato_norm in mapa:
            return mapa[candidato_norm]

    for coluna_norm, coluna_original in mapa.items():
        for candidato in candidatos:
            candidato_norm = normalizar(candidato)
            if candidato_norm and candidato_norm in coluna_norm:
                return coluna_original

    return None


def _linhas_texto_para_itens(linhas):
    itens = []

    for linha in linhas:
        texto = re.sub(r"\s+", " ", str(linha)).strip()
        if not texto:
            continue

        texto_norm = normalizar(texto)
        if texto_norm in {"item descricao quantidade", "descricao quantidade", "item especificacao qtd"}:
            continue

        quantidade = None
        descricao = texto
        item = str(len(itens) + 1)

        match_item = re.match(r"^\s*(?:item\s*)?(\d{1,4})[\s\-.)]+(.+)$", texto, flags=re.I)
        if match_item:
            item = match_item.group(1)
            descricao = match_item.group(2).strip()

        match_qtd = re.search(
            r"(?:qtd|qtde|quantidade)\s*[:\-]?\s*([\d.,]+)\s*(?:un|und|unid|unidade|unidades)?|\b([\d.,]+)\s*(?:un|und|unid|unidade|unidades)\b",
            descricao,
            flags=re.I,
        )
        if match_qtd:
            quantidade = converter_numero(match_qtd.group(1) or match_qtd.group(2))
            descricao = (descricao[:match_qtd.start()] + descricao[match_qtd.end():]).strip(" -;,")

        if len(normalizar(descricao)) < 8:
            continue

        itens.append({
            "item": item,
            "descricao": descricao,
            "quantidade": quantidade,
        })

    return pd.DataFrame(itens)


def _parece_inteiro(texto):
    return re.fullmatch(r"\d{1,6}", str(texto).strip()) is not None


def _parece_quantidade(texto):
    return re.fullmatch(r"\d+(?:[.,]\d+)?", str(texto).strip()) is not None


def _parece_unidade(texto):
    return normalizar(texto) in {
        "un", "und", "unid", "unidade", "unidades", "m", "mt", "m2", "m3",
        "kg", "g", "l", "lt", "cx", "pct", "pc", "peca", "pecas", "par",
        "rolo", "barra", "metro", "metros", "jg", "jogo", "jogos", "kit",
        "conjunto"
    }


def _parece_valor_monetario(texto):
    return re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2,4}|\d+,\d{2,4}", str(texto).strip()) is not None


def _linhas_tabela_pdf_para_itens(linhas):
    linhas_limpas = [
        re.sub(r"\s+", " ", str(linha)).strip()
        for linha in linhas
        if str(linha).strip()
    ]
    itens = []
    i = 0

    while i < len(linhas_limpas) - 4:
        if not (
            _parece_inteiro(linhas_limpas[i])
            and _parece_inteiro(linhas_limpas[i + 1])
            and _parece_quantidade(linhas_limpas[i + 2])
            and _parece_unidade(linhas_limpas[i + 3])
        ):
            i += 1
            continue

        item = linhas_limpas[i]
        quantidade = converter_numero(linhas_limpas[i + 2])
        unidade = linhas_limpas[i + 3]
        descricao_partes = []
        j = i + 4

        while j < len(linhas_limpas):
            linha = linhas_limpas[j]

            if (
                _parece_valor_monetario(linha)
                and j + 1 < len(linhas_limpas)
                and _parece_valor_monetario(linhas_limpas[j + 1])
            ):
                j += 2
                break

            if (
                j + 4 < len(linhas_limpas)
                and _parece_inteiro(linhas_limpas[j])
                and _parece_inteiro(linhas_limpas[j + 1])
                and _parece_quantidade(linhas_limpas[j + 2])
                and _parece_unidade(linhas_limpas[j + 3])
                and descricao_partes
            ):
                break

            if normalizar(linha) not in {"valor", "unitario", "total", "r", "rs"}:
                descricao_partes.append(linha)
            j += 1

        descricao = " ".join(descricao_partes)
        descricao = re.sub(r"\s+([,.;:)])", r"\1", descricao)
        descricao = re.sub(r"([(-])\s+", r"\1", descricao).strip(" -;")

        if len(normalizar(descricao)) >= 8:
            itens.append({
                "item": item,
                "descricao": descricao,
                "quantidade": quantidade,
                "unidade": unidade,
            })

        i = max(j, i + 1)

    return pd.DataFrame(itens)


def _extrair_linhas_docx(bytes_arquivo):
    linhas = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    with zipfile.ZipFile(BytesIO(bytes_arquivo)) as docx:
        xml_documento = docx.read("word/document.xml")

    raiz = ET.fromstring(xml_documento)

    for tabela in raiz.findall(".//w:tbl", ns):
        for linha in tabela.findall(".//w:tr", ns):
            celulas = []
            for celula in linha.findall(".//w:tc", ns):
                textos = [
                    t.text or ""
                    for t in celula.findall(".//w:t", ns)
                ]
                celulas.append(" ".join(textos).strip())
            if any(celulas):
                linhas.append(" | ".join(celulas))

    for paragrafo in raiz.findall(".//w:p", ns):
        textos = [
            t.text or ""
            for t in paragrafo.findall(".//w:t", ns)
        ]
        linha = " ".join(textos).strip()
        if linha:
            linhas.append(linha)

    return linhas


def carregar_itens_documento(arquivo_enviado):
    if arquivo_enviado is None:
        return pd.DataFrame()

    bytes_arquivo = arquivo_enviado.getvalue()
    nome = arquivo_enviado.name.lower()

    if nome.endswith(".xlsx"):
        return carregar_planilha_itens(arquivo_enviado)

    if nome.endswith(".docx"):
        return _linhas_texto_para_itens(_extrair_linhas_docx(bytes_arquivo))

    if nome.endswith(".pdf"):
        texto = extrair_texto_normativo(arquivo_enviado.name, bytes_arquivo)
        itens_tabela = _linhas_tabela_pdf_para_itens(texto.splitlines())
        if not itens_tabela.empty:
            return itens_tabela
        return _linhas_texto_para_itens(texto.splitlines())

    raise ValueError("Formato nao suportado. Envie XLSX, DOCX ou PDF.")


def carregar_planilha_itens(arquivo_enviado):
    if arquivo_enviado is None:
        return pd.DataFrame()

    bytes_arquivo = arquivo_enviado.getvalue()
    df = pd.read_excel(BytesIO(bytes_arquivo), dtype=str)
    df = df.dropna(how="all")

    coluna_item = localizar_coluna(df, ["item", "nr item", "numero item", "n"])
    coluna_descricao = localizar_coluna(df, [
        "descricao",
        "descricao do item",
        "objeto",
        "material",
        "produto",
        "especificacao",
    ])
    coluna_quantidade = localizar_coluna(df, [
        "quantidade",
        "qtd",
        "qtde",
        "quant",
    ])

    if coluna_descricao is None:
        bruto = pd.read_excel(BytesIO(bytes_arquivo), header=None, dtype=str)
        melhor_linha = None
        melhor_pontos = 0

        for indice, row in bruto.head(30).iterrows():
            valores = [normalizar(valor) for valor in row.fillna("").tolist()]
            texto = " ".join(valores)
            pontos = 0
            if "descricao" in texto:
                pontos += 3
            if "item" in valores:
                pontos += 2
            if any(v in {"qtde", "qtd", "quantidade"} for v in valores):
                pontos += 2

            if pontos > melhor_pontos:
                melhor_pontos = pontos
                melhor_linha = indice

        if melhor_linha is not None and melhor_pontos >= 3:
            df = pd.read_excel(BytesIO(bytes_arquivo), header=melhor_linha, dtype=str)
            df = df.dropna(how="all")
            coluna_item = localizar_coluna(df, ["item", "nr item", "numero item", "n"])
            coluna_descricao = localizar_coluna(df, [
                "descricao",
                "descricao do item",
                "objeto",
                "material",
                "produto",
                "especificacao",
            ])
            coluna_quantidade = localizar_coluna(df, [
                "quantidade",
                "qtd",
                "qtde",
                "quant",
            ])

    if coluna_descricao is None:
        raise ValueError("Nao encontrei uma coluna de descricao na planilha.")

    itens = []
    for indice, row in df.iterrows():
        descricao = str(row.get(coluna_descricao, "")).strip()
        if not descricao or descricao.lower() in {"nan", "none"}:
            continue

        quantidade = converter_numero(row.get(coluna_quantidade, "")) if coluna_quantidade else None
        item = str(row.get(coluna_item, indice + 1)).strip() if coluna_item else str(len(itens) + 1)

        itens.append({
            "item": item,
            "descricao": descricao,
            "quantidade": quantidade,
        })

    return pd.DataFrame(itens)


def classificar_status_lote(conformidade, resultados):
    if not resultados:
        return "Sem resultado"

    if conformidade["total_precos"] < 3:
        return "Revisar"

    if conformidade["precos_aproveitados"] < 3:
        return "Revisar"

    if conformidade["alertas"]:
        return "Atencao"

    return "OK"


def montar_linhas_cesta(
    itens_df,
    qtd_faixa_padrao=0.30,
    limite_precos_item=5,
    fontes_selecionadas=None,
    perfil_codigo="joia_rs_5337",
    responsavel="",
    metodo_preferido="auto",
    justificativas=None,
    consultar_fontes_adicionais_todos=False,
):
    fontes_selecionadas = fontes_selecionadas or ["LicitaCon"]
    justificativas = justificativas or {}
    resumo = []
    detalhes = []
    avisos_integracao_lote = []

    total = len(itens_df)
    barra = st.progress(0)
    status_texto = st.empty()

    for posicao, item in enumerate(itens_df.to_dict("records"), start=1):
        descricao = item["descricao"]
        quantidade = item.get("quantidade")

        if quantidade is None or quantidade <= 0:
            qtd_min = 0
            qtd_max = 999999999
        else:
            qtd_min = max(0, quantidade * (1 - qtd_faixa_padrao))
            qtd_max = quantidade * (1 + qtd_faixa_padrao)

        status_texto.write(f"Pesquisando item {posicao}/{total}: {descricao[:90]}")

        criterios = extrair_criterios_com_ia(descricao)
        resultados = []
        fontes_normalizadas = []
        erro = ""

        if "LicitaCon" in fontes_selecionadas:
            try:
                criterios, resultados, estatisticas = executar_pesquisa_sqlite(
                    descricao_busca=descricao,
                    qtd_min=qtd_min,
                    qtd_max=qtd_max,
                    limite_candidatos=MAX_CANDIDATOS_LOTE,
                )
                fontes_normalizadas.extend(fontes_de_resultados_licitacon(resultados))
            except Exception as exc:
                erro = str(exc)

        conformidade = avaliar_conformidade_pesquisa(
            fontes_normalizadas or resultados,
            descricao_objeto=descricao,
            responsavel=responsavel,
            justificativa_menos_tres=justificativas.get("menos_tres", ""),
            justificativa_descartes=justificativas.get("descartes", ""),
            metodo_preferido=metodo_preferido,
            perfil_codigo=perfil_codigo,
        )

        fontes_externas = [fonte for fonte in fontes_selecionadas if fonte != "LicitaCon"]
        deve_buscar_fontes_externas = (
            bool(fontes_externas)
            and (
                consultar_fontes_adicionais_todos
                or "LicitaCon" not in fontes_selecionadas
                or conformidade.get("precos_aproveitados", 0) < 3
            )
        )

        if deve_buscar_fontes_externas:
            status_texto.write(
                f"Complementando item {posicao}/{total} em fontes externas: {descricao[:80]}"
            )
            adicionais, avisos_integracao = executar_fontes_adicionais(
                descricao,
                fontes_selecionadas,
                limite_pncp=limite_precos_item,
                limite_web=limite_precos_item,
            )
            avisos_integracao_lote.extend(
                f"Item {item.get('item', posicao)} - {aviso}"
                for aviso in avisos_integracao
            )
            fontes_normalizadas.extend(adicionais)
            resultados = resultados + resultados_de_fontes(adicionais)
            conformidade = avaliar_conformidade_pesquisa(
                fontes_normalizadas or resultados,
                descricao_objeto=descricao,
                responsavel=responsavel,
                justificativa_menos_tres=justificativas.get("menos_tres", ""),
                justificativa_descartes=justificativas.get("descartes", ""),
                metodo_preferido=metodo_preferido,
                perfil_codigo=perfil_codigo,
            )
        status = "Erro" if erro and not resultados else classificar_status_lote(conformidade, resultados)

        resumo.append({
            "Item": item.get("item", posicao),
            "Descricao original": descricao,
            "Quantidade solicitada": quantidade if quantidade is not None else "",
            "Status": status,
            "Fontes consultadas": ", ".join(fontes_selecionadas),
            "Origens encontradas": ", ".join(conformidade.get("fontes_consultadas", [])),
            "Resultados encontrados": len(resultados),
            "Precos validos": conformidade["total_precos"],
            "Precos dentro do prazo normativo": conformidade.get("precos_no_prazo"),
            "Precos aproveitados": conformidade["precos_aproveitados"],
            "Precos descartados": conformidade["precos_descartados"],
            "Menor preco": conformidade["menor"],
            "Media": conformidade["media"],
            "Mediana": conformidade["mediana"],
            "Metodo sugerido": conformidade["metodo_sugerido"],
            "Valor sugerido": conformidade["valor_sugerido"],
            "Descricao sugerida LicitaCon": criterios.get("descricao_sugerida_licitacon", ""),
            "Alertas": " | ".join(conformidade["alertas"]),
            "Erro": erro,
        })

        for ordem, resultado in enumerate(resultados[:limite_precos_item], start=1):
            detalhes.append({
                "Item": item.get("item", posicao),
                "Ordem": ordem,
                "Status item": status,
                "Descricao original": descricao,
                "Descricao encontrada": resultado.get("descricao", ""),
                "Origem": resultado.get("fonte_base") or resultado.get("modo_busca", ""),
                "Score": resultado.get("score", ""),
                "Tipo busca": resultado.get("modo_busca", ""),
                "Orgao": resultado.get("orgao", ""),
                "Municipio fonte": resultado.get("municipio_fonte", ""),
                "Grupo regional": resultado.get("grupo_regional", ""),
                "Fonte base": resultado.get("fonte_base", ""),
                "Licitacao": f"{resultado.get('nr', '')}/{resultado.get('ano', '')}",
                "Quantidade encontrada": resultado.get("qtd", ""),
                "Unidade": resultado.get("unidade", ""),
                "Valor unitario": converter_numero(resultado.get("valor_unitario")),
                "Valor total": converter_numero(resultado.get("valor_total")),
                "Data abertura": resultado.get("data", ""),
                "Data homologacao": resultado.get("data_homologacao", ""),
                "Vencedor": resultado.get("vencedor", ""),
                "CPF/CNPJ": resultado.get("cpf_cnpj", ""),
                "Link/Evidencia": resultado.get("link_licitacon", ""),
                "Observacoes": resultado.get("avisos_tecnicos", ""),
            })

        barra.progress(posicao / total)

    status_texto.write("Pesquisa por planilha concluida.")
    return pd.DataFrame(resumo), pd.DataFrame(detalhes), avisos_integracao_lote


def gerar_excel_cesta(resumo_df, detalhes_df):
    saida = BytesIO()

    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, sheet_name="Resumo", index=False)
        detalhes_df.to_excel(writer, sheet_name="Precos encontrados", index=False)

    return saida.getvalue()


def _pdf_escape(texto):
    texto = "" if texto is None else str(texto)
    texto = texto.encode("latin-1", errors="replace").decode("latin-1")
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_wrap(texto, largura=92):
    texto = re.sub(r"\s+", " ", "" if texto is None else str(texto)).strip()
    if not texto:
        return [""]
    palavras = texto.split()
    linhas = []
    linha = ""
    for palavra in palavras:
        tentativa = f"{linha} {palavra}".strip()
        if len(tentativa) <= largura:
            linha = tentativa
        else:
            if linha:
                linhas.append(linha)
            linha = palavra[:largura]
    if linha:
        linhas.append(linha)
    return linhas


def _pdf_formatar_valor(valor):
    numero = converter_numero(valor)
    return formatar_moeda(numero) if numero is not None else "-"


def _media_valores(valores):
    valores = [valor for valor in valores if valor is not None and valor > 0]
    if not valores:
        return None
    return sum(valores) / len(valores)


def _mediana_valores(valores):
    valores = sorted(valor for valor in valores if valor is not None and valor > 0)
    if not valores:
        return None
    meio = len(valores) // 2
    if len(valores) % 2:
        return valores[meio]
    return (valores[meio - 1] + valores[meio]) / 2


def _saneados_para_relatorio(valores):
    valores = [valor for valor in valores if valor is not None and valor > 0]
    if len(valores) < 3:
        return valores

    mediana_valor = _mediana_valores(valores)
    if not mediana_valor:
        return valores

    filtrados = [
        valor for valor in valores
        if mediana_valor / 3 <= valor <= mediana_valor * 3
    ]
    return filtrados if len(filtrados) >= 3 else valores


def _estatisticas_relatorio_item(grupo):
    if grupo.empty:
        return None, None, None
    valores = [
        converter_numero(valor)
        for valor in grupo.get("Valor unitario", pd.Series(dtype=float)).tolist()
    ]
    saneados = _saneados_para_relatorio(valores)
    return (
        _media_valores(saneados),
        _mediana_valores(saneados),
        _media_valores(saneados),
    )


def _criar_pdf_textual(linhas):
    largura_pagina = 595
    altura_pagina = 842
    margem_x = 42
    margem_y = 42
    y_inicial = altura_pagina - margem_y
    y_min = margem_y
    paginas = []
    pagina_atual = {"comandos": [], "links": []}
    y = y_inicial

    def nova_pagina():
        nonlocal pagina_atual, y
        if pagina_atual["comandos"] or pagina_atual["links"]:
            paginas.append(pagina_atual)
        pagina_atual = {"comandos": [], "links": []}
        y = y_inicial

    def escrever(texto="", tamanho=9, negrito=False, link=None, recuo=0):
        nonlocal y
        altura_linha = tamanho + 4
        if y - altura_linha < y_min:
            nova_pagina()

        fonte = "F2" if negrito else "F1"
        x = margem_x + recuo
        pagina_atual["comandos"].append(
            f"BT /{fonte} {tamanho} Tf {x} {y} Td ({_pdf_escape(texto)}) Tj ET"
        )
        if link:
            pagina_atual["links"].append({
                "rect": [x, y - 2, min(largura_pagina - margem_x, x + 470), y + tamanho + 2],
                "url": link,
            })
        y -= altura_linha

    for linha in linhas:
        if linha.get("quebra"):
            nova_pagina()
            continue
        if linha.get("espaco"):
            y -= linha.get("espaco", 8)
            if y < y_min:
                nova_pagina()
            continue
        escrever(
            linha.get("texto", ""),
            tamanho=linha.get("tamanho", 9),
            negrito=linha.get("negrito", False),
            link=linha.get("link"),
            recuo=linha.get("recuo", 0),
        )

    if pagina_atual["comandos"] or pagina_atual["links"]:
        paginas.append(pagina_atual)

    objetos = []

    def adicionar_objeto(conteudo):
        objetos.append(conteudo)
        return len(objetos)

    catalogo_id = adicionar_objeto("<< /Type /Catalog /Pages 2 0 R >>")
    paginas_id = adicionar_objeto("")
    fonte_regular_id = adicionar_objeto("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    fonte_negrito_id = adicionar_objeto("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pagina_ids = []

    for pagina in paginas:
        stream = "\n".join(pagina["comandos"]).encode("latin-1", errors="replace")
        conteudo_id = adicionar_objeto(
            f"<< /Length {len(stream)} >>\nstream\n"
            + stream.decode("latin-1")
            + "\nendstream"
        )
        anotacoes_ids = []
        for link in pagina["links"]:
            rect = " ".join(str(round(v, 2)) for v in link["rect"])
            anotacoes_ids.append(adicionar_objeto(
                "<< /Type /Annot /Subtype /Link "
                f"/Rect [{rect}] /Border [0 0 0] "
                f"/A << /S /URI /URI ({_pdf_escape(link['url'])}) >> >>"
            ))
        anotacoes = (
            " /Annots [" + " ".join(f"{obj_id} 0 R" for obj_id in anotacoes_ids) + "]"
            if anotacoes_ids
            else ""
        )
        pagina_id = adicionar_objeto(
            "<< /Type /Page "
            f"/Parent {paginas_id} 0 R "
            f"/MediaBox [0 0 {largura_pagina} {altura_pagina}] "
            f"/Resources << /Font << /F1 {fonte_regular_id} 0 R /F2 {fonte_negrito_id} 0 R >> >> "
            f"/Contents {conteudo_id} 0 R{anotacoes} >>"
        )
        pagina_ids.append(pagina_id)

    objetos[paginas_id - 1] = (
        "<< /Type /Pages /Kids ["
        + " ".join(f"{pagina_id} 0 R" for pagina_id in pagina_ids)
        + f"] /Count {len(pagina_ids)} >>"
    )

    saida = BytesIO()
    saida.write(b"%PDF-1.4\n")
    offsets = [0]
    for indice, conteudo in enumerate(objetos, start=1):
        offsets.append(saida.tell())
        saida.write(f"{indice} 0 obj\n{conteudo}\nendobj\n".encode("latin-1", errors="replace"))

    xref_pos = saida.tell()
    saida.write(f"xref\n0 {len(objetos) + 1}\n".encode("ascii"))
    saida.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        saida.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    saida.write(
        (
            "trailer\n"
            f"<< /Size {len(objetos) + 1} /Root {catalogo_id} 0 R >>\n"
            "startxref\n"
            f"{xref_pos}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return saida.getvalue()


def gerar_pdf_cesta(resumo_df, detalhes_df, responsavel, metodo, perfil_nome, fontes_selecionadas):
    linhas = [
        {"texto": "Dossie da Pesquisa de Precos", "tamanho": 17, "negrito": True},
        {"texto": f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", "tamanho": 9},
        {"texto": f"Responsavel: {responsavel or '-'}", "tamanho": 10},
        {"texto": f"Perfil normativo: {perfil_nome or '-'}", "tamanho": 10},
        {"texto": f"Metodologia de formacao do preco: {metodo or '-'}", "tamanho": 10},
        {"texto": f"Fontes selecionadas: {', '.join(fontes_selecionadas or []) or '-'}", "tamanho": 10},
        {"espaco": 10},
        {"texto": "Resumo dos itens pesquisados", "tamanho": 13, "negrito": True},
    ]

    for _, item in resumo_df.iterrows():
        linhas.append({"espaco": 6})
        titulo = (
            f"Item {item.get('Item', '')} - {item.get('Status', '')} - "
            f"valor sugerido {_pdf_formatar_valor(item.get('Valor sugerido'))}"
        )
        linhas.append({"texto": titulo, "tamanho": 11, "negrito": True})
        for trecho in _pdf_wrap(item.get("Descricao original", ""), largura=98):
            linhas.append({"texto": trecho, "tamanho": 9})
        linhas.append({
            "texto": (
                f"Qtd solicitada: {item.get('Quantidade solicitada', '-')}; "
                f"precos validos: {item.get('Precos validos', 0)}; "
                f"origens encontradas: {item.get('Origens encontradas', '-') or '-'}"
            ),
            "tamanho": 9,
        })
        alertas = item.get("Alertas", "")
        if alertas:
            for trecho in _pdf_wrap(f"Alertas: {alertas}", largura=98):
                linhas.append({"texto": trecho, "tamanho": 8})

    linhas.append({"quebra": True})
    linhas.append({"texto": "Fontes e evidencias por item", "tamanho": 14, "negrito": True})

    if detalhes_df.empty:
        linhas.append({"texto": "Nenhuma fonte encontrada.", "tamanho": 10})
    else:
        for item_id, grupo in detalhes_df.groupby("Item", sort=False):
            linhas.append({"espaco": 8})
            descricao_original = grupo.iloc[0].get("Descricao original", "")
            linhas.append({"texto": f"Item {item_id}", "tamanho": 12, "negrito": True})
            for trecho in _pdf_wrap(descricao_original, largura=98):
                linhas.append({"texto": trecho, "tamanho": 9})

            for _, fonte in grupo.iterrows():
                cabecalho = (
                    f"{fonte.get('Ordem', '')}. {fonte.get('Origem', '-') or '-'} | "
                    f"{_pdf_formatar_valor(fonte.get('Valor unitario'))} | "
                    f"{fonte.get('Orgao', '-') or '-'}"
                )
                linhas.append({"texto": cabecalho, "tamanho": 9, "negrito": True, "recuo": 10})
                for trecho in _pdf_wrap(fonte.get("Descricao encontrada", ""), largura=92):
                    linhas.append({"texto": trecho, "tamanho": 8, "recuo": 10})

                fornecedor = fonte.get("Vencedor", "")
                if fornecedor:
                    linhas.append({"texto": f"Fornecedor: {fornecedor}", "tamanho": 8, "recuo": 10})

                data_ref = fonte.get("Data homologacao") or fonte.get("Data abertura") or ""
                linhas.append({
                    "texto": (
                        f"Qtd: {fonte.get('Quantidade encontrada', '-')}; "
                        f"Unidade: {fonte.get('Unidade', '-')}; "
                        f"Data: {data_ref or '-'}"
                    ),
                    "tamanho": 8,
                    "recuo": 10,
                })

                link = fonte.get("Link/Evidencia", "")
                if link:
                    for indice, trecho in enumerate(_pdf_wrap(f"Link: {link}", largura=92)):
                        linhas.append({
                            "texto": trecho,
                            "tamanho": 8,
                            "recuo": 10,
                            "link": link if indice == 0 and str(link).startswith("http") else None,
                        })

                observacoes = fonte.get("Observacoes", "")
                if observacoes:
                    for trecho in _pdf_wrap(f"Observacoes: {observacoes}", largura=92):
                        linhas.append({"texto": trecho, "tamanho": 8, "recuo": 10})

    return _criar_pdf_textual(linhas)


def _pdf_texto_curto(texto, limite):
    texto = re.sub(r"\s+", " ", "" if texto is None else str(texto)).strip()
    if len(texto) <= limite:
        return texto
    return texto[: max(0, limite - 3)].rstrip() + "..."


def _criar_pdf_cesta_visual(resumo_df, detalhes_df, responsavel, metodo, perfil_nome, fontes_selecionadas):
    largura_pagina = 842
    altura_pagina = 595
    margem = 36
    paginas = []
    pagina = None
    y = 0

    azul = "0.07 0.18 0.34"
    azul_claro = "0.90 0.94 0.98"
    cinza_claro = "0.94 0.95 0.97"
    cinza_linha = "0.78 0.81 0.86"
    texto = "0.12 0.15 0.20"

    def nova_pagina(titulo="Dossie da Pesquisa de Precos"):
        nonlocal pagina, y
        if pagina is not None:
            paginas.append(pagina)
        pagina = {"comandos": [], "links": []}
        y = altura_pagina - margem
        retangulo(margem, y - 26, largura_pagina - (2 * margem), 26, azul, stroke=False)
        escrever(titulo, margem + 12, y - 18, 11, True, cor="1 1 1")
        escrever(
            datetime.now().strftime("Gerado em %d/%m/%Y as %H:%M"),
            largura_pagina - margem - 165,
            y - 18,
            8,
            False,
            cor="1 1 1",
        )
        y -= 46

    def retangulo(x, y_base, w, h, cor, stroke=True):
        if stroke:
            pagina["comandos"].append(f"{cor} rg {x} {y_base} {w} {h} re f")
            pagina["comandos"].append(f"{cinza_linha} RG {x} {y_base} {w} {h} re S")
        else:
            pagina["comandos"].append(f"{cor} rg {x} {y_base} {w} {h} re f")

    def linha(x1, y1, x2, y2, cor=cinza_linha):
        pagina["comandos"].append(f"{cor} RG {x1} {y1} m {x2} {y2} l S")

    def escrever(valor, x, y_texto, tamanho=9, negrito=False, cor=texto, link=None):
        fonte = "F2" if negrito else "F1"
        pagina["comandos"].append(
            f"{cor} rg BT /{fonte} {tamanho} Tf {x} {y_texto} Td ({_pdf_escape(valor)}) Tj ET"
        )
        if link:
            pagina["links"].append({
                "rect": [x, y_texto - 2, min(largura_pagina - margem, x + 115), y_texto + tamanho + 3],
                "url": link,
            })

    def escrever_bloco(valor, x, y_texto, largura_chars, tamanho=8, max_linhas=2, cor=texto):
        linhas = _pdf_wrap(valor, largura=largura_chars)[:max_linhas]
        atual = y_texto
        for parte in linhas:
            escrever(parte, x, atual, tamanho, False, cor=cor)
            atual -= tamanho + 3
        return atual

    def garantir(altura):
        if y - altura < margem:
            nova_pagina()

    def cartao(x, largura, titulo, valor):
        retangulo(x, y - 54, largura, 54, azul_claro)
        escrever(titulo.upper(), x + 12, y - 20, 8, True, cor="0.30 0.36 0.45")
        escrever(valor, x + 12, y - 40, 14, True, cor="0.05 0.33 0.58")

    def tabela_item(grupo):
        nonlocal y
        colunas = [
            ("DESCRICAO", 285),
            ("VALOR\nUNITARIO", 72),
            ("MEDIDA", 55),
            ("N COMPRA", 68),
            ("DATA", 68),
            ("ORGAO", 150),
            ("FONTE", 55),
        ]
        x0 = margem
        largura_total = sum(largura for _, largura in colunas)
        garantir(94)
        retangulo(x0, y - 25, largura_total, 25, azul, stroke=False)
        escrever("INCISO II - CONTRATACOES PUBLICAS", x0 + 10, y - 17, 10, True, cor="1 1 1")
        y -= 35

        retangulo(x0, y - 25, largura_total, 25, cinza_claro)
        x = x0
        for nome, largura in colunas:
            partes = nome.split("\n")
            escrever(partes[0], x + 5, y - 11, 7, True, cor="0.25 0.29 0.36")
            if len(partes) > 1:
                escrever(partes[1], x + 5, y - 20, 7, True, cor="0.25 0.29 0.36")
            linha(x, y - 25, x, y, cor="0.84 0.86 0.90")
            x += largura
        linha(x0 + largura_total, y - 25, x0 + largura_total, y, cor="0.84 0.86 0.90")
        y -= 25

        if grupo.empty:
            retangulo(x0, y - 30, largura_total, 30, "1 1 1")
            escrever("Nenhum preco encontrado para este item.", x0 + 8, y - 19, 8)
            y -= 36
            return

        for _, fonte in grupo.iterrows():
            garantir(44)
            altura_linha = 42
            retangulo(x0, y - altura_linha, largura_total, altura_linha, "1 1 1")
            x = x0
            descricao = fonte.get("Descricao encontrada", "")
            escrever_bloco(descricao, x + 5, y - 13, 47, tamanho=7, max_linhas=3)
            x += colunas[0][1]
            escrever(_pdf_formatar_valor(fonte.get("Valor unitario")), x + 5, y - 18, 8)
            x += colunas[1][1]
            escrever(_pdf_texto_curto(fonte.get("Unidade", ""), 9), x + 5, y - 18, 8)
            x += colunas[2][1]
            compra = str(fonte.get("Licitacao", "")).strip("/")
            escrever(_pdf_texto_curto(compra or "-", 11), x + 5, y - 18, 8)
            x += colunas[3][1]
            data_ref = fonte.get("Data homologacao") or fonte.get("Data abertura") or "-"
            escrever(_pdf_texto_curto(data_ref, 10), x + 5, y - 18, 8)
            x += colunas[4][1]
            escrever_bloco(fonte.get("Orgao", ""), x + 5, y - 13, 24, tamanho=7, max_linhas=3)
            x += colunas[5][1]
            link = str(fonte.get("Link/Evidencia", "") or "")
            origem = _pdf_texto_curto(fonte.get("Origem") or fonte.get("Fonte base") or "-", 9)
            escrever(origem, x + 5, y - 14, 7, True)
            if link.startswith("http"):
                escrever("abrir", x + 5, y - 29, 7, False, cor="0.05 0.33 0.58", link=link)
            y -= altura_linha

    nova_pagina()
    escrever("Responsavel:", margem, y, 8, True)
    escrever(responsavel or "-", margem + 72, y, 8)
    escrever("Perfil normativo:", margem + 250, y, 8, True)
    escrever(_pdf_texto_curto(perfil_nome or "-", 56), margem + 338, y, 8)
    y -= 14
    escrever("Metodo:", margem, y, 8, True)
    escrever(metodo or "-", margem + 43, y, 8)
    escrever("Fontes selecionadas:", margem + 250, y, 8, True)
    escrever(", ".join(fontes_selecionadas or []) or "-", margem + 355, y, 8)
    y -= 18

    for indice, item in resumo_df.iterrows():
        if indice > 0:
            nova_pagina()

        item_id = item.get("Item", indice + 1)
        grupo_item = detalhes_df[detalhes_df["Item"].astype(str) == str(item_id)] if not detalhes_df.empty else pd.DataFrame()
        media_relatorio, mediana_relatorio, media_saneada_relatorio = _estatisticas_relatorio_item(grupo_item)

        escrever(f"ITEM {item_id}", margem, y, 17, True, cor="0.05 0.33 0.58")
        y -= 17
        escrever_bloco(item.get("Descricao original", ""), margem, y, 118, tamanho=8, max_linhas=3)
        y -= 36
        unidade = ""
        if not grupo_item.empty:
            unidade = grupo_item.iloc[0].get("Unidade", "")
        escrever(
            f"Unidade: {unidade or '-'}  |  Quantidade: {item.get('Quantidade solicitada', '-') or '-'}",
            margem,
            y,
            8,
            True,
        )
        y -= 22

        largura_cartao = 145
        x_cartao = margem + 12
        cartao(x_cartao, largura_cartao, "Media", _pdf_formatar_valor(media_relatorio))
        cartao(x_cartao + largura_cartao + 18, largura_cartao, "Mediana", _pdf_formatar_valor(mediana_relatorio))
        cartao(
            x_cartao + (largura_cartao + 18) * 2,
            largura_cartao,
            "Media saneada",
            _pdf_formatar_valor(media_saneada_relatorio),
        )
        y -= 72

        tabela_item(grupo_item)

    if pagina is not None:
        paginas.append(pagina)

    objetos = []

    def adicionar_objeto(conteudo):
        objetos.append(conteudo)
        return len(objetos)

    catalogo_id = adicionar_objeto("<< /Type /Catalog /Pages 2 0 R >>")
    paginas_id = adicionar_objeto("")
    fonte_regular_id = adicionar_objeto("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    fonte_negrito_id = adicionar_objeto("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pagina_ids = []

    for item_pagina in paginas:
        stream = "\n".join(item_pagina["comandos"]).encode("latin-1", errors="replace")
        conteudo_id = adicionar_objeto(
            f"<< /Length {len(stream)} >>\nstream\n"
            + stream.decode("latin-1")
            + "\nendstream"
        )
        anotacoes_ids = []
        for link in item_pagina["links"]:
            rect = " ".join(str(round(v, 2)) for v in link["rect"])
            anotacoes_ids.append(adicionar_objeto(
                "<< /Type /Annot /Subtype /Link "
                f"/Rect [{rect}] /Border [0 0 0] "
                f"/A << /S /URI /URI ({_pdf_escape(link['url'])}) >> >>"
            ))
        anotacoes = (
            " /Annots [" + " ".join(f"{obj_id} 0 R" for obj_id in anotacoes_ids) + "]"
            if anotacoes_ids
            else ""
        )
        pagina_id = adicionar_objeto(
            "<< /Type /Page "
            f"/Parent {paginas_id} 0 R "
            f"/MediaBox [0 0 {largura_pagina} {altura_pagina}] "
            f"/Resources << /Font << /F1 {fonte_regular_id} 0 R /F2 {fonte_negrito_id} 0 R >> >> "
            f"/Contents {conteudo_id} 0 R{anotacoes} >>"
        )
        pagina_ids.append(pagina_id)

    objetos[paginas_id - 1] = (
        "<< /Type /Pages /Kids ["
        + " ".join(f"{pagina_id} 0 R" for pagina_id in pagina_ids)
        + f"] /Count {len(pagina_ids)} >>"
    )

    saida = BytesIO()
    saida.write(b"%PDF-1.4\n")
    offsets = [0]
    for indice_obj, conteudo in enumerate(objetos, start=1):
        offsets.append(saida.tell())
        saida.write(f"{indice_obj} 0 obj\n{conteudo}\nendobj\n".encode("latin-1", errors="replace"))

    xref_pos = saida.tell()
    saida.write(f"xref\n0 {len(objetos) + 1}\n".encode("ascii"))
    saida.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        saida.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    saida.write(
        (
            "trailer\n"
            f"<< /Size {len(objetos) + 1} /Root {catalogo_id} 0 R >>\n"
            "startxref\n"
            f"{xref_pos}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return saida.getvalue()


def gerar_pdf_cesta(resumo_df, detalhes_df, responsavel, metodo, perfil_nome, fontes_selecionadas):
    return _criar_pdf_cesta_visual(
        resumo_df=resumo_df,
        detalhes_df=detalhes_df,
        responsavel=responsavel,
        metodo=metodo,
        perfil_nome=perfil_nome,
        fontes_selecionadas=fontes_selecionadas,
    )


def fontes_de_resultados_licitacon(resultados):
    return [
        resultado_licitacon_para_fonte(resultado).to_dict()
        for resultado in resultados
    ]


def resultados_de_fontes(fontes):
    return [fonte_para_resultado(fonte) for fonte in fontes]


def executar_fontes_adicionais(descricao_busca, fontes_selecionadas, limite_pncp=20, limite_web=10):
    fontes = []
    avisos = []

    if "PNCP" in fontes_selecionadas:
        try:
            fontes.extend([fonte.to_dict() for fonte in buscar_pncp(descricao_busca, limite=limite_pncp)])
        except Exception as erro:
            avisos.append(f"PNCP: {erro}")

    if "Internet" in fontes_selecionadas:
        try:
            fontes_web, aviso_web = buscar_web(descricao_busca, limite=limite_web)
            fontes.extend([fonte.to_dict() for fonte in fontes_web])
            if aviso_web:
                avisos.append(f"Internet: {aviso_web}")
        except Exception as erro:
            avisos.append(f"Internet: {erro}")

    if "Fornecedores" in fontes_selecionadas:
        try:
            fontes.extend([fonte.to_dict() for fonte in buscar_fornecedores(descricao_busca)])
        except Exception as erro:
            avisos.append(f"Fornecedores: {erro}")

    return fontes, avisos


def gerar_excel_dossie(descricao_busca, responsavel, criterios, resultados, fontes, conformidade, justificativas):
    saida = BytesIO()
    fontes_linhas = fontes_para_dataframe_linhas(fontes)
    resumo = pd.DataFrame([{
        "Descricao do objeto": descricao_busca,
        "Responsavel": responsavel,
        "Perfil normativo": conformidade.get("perfil_normativo", ""),
        "Base legal": " | ".join(conformidade.get("base_legal", [])),
        "Data da pesquisa": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "Fontes consultadas": ", ".join(conformidade.get("fontes_consultadas", [])),
        "Total de precos": conformidade.get("total_precos"),
        "Precos dentro do prazo normativo": conformidade.get("precos_no_prazo"),
        "Precos aproveitados": conformidade.get("precos_aproveitados"),
        "Precos descartados": conformidade.get("precos_descartados"),
        "Metodo sugerido": conformidade.get("metodo_sugerido"),
        "Valor sugerido": conformidade.get("valor_sugerido"),
        "Justificativa menos de 3 precos": justificativas.get("menos_tres", ""),
        "Justificativa descartes": justificativas.get("descartes", ""),
        "Justificativa metodologia": justificativas.get("metodologia", ""),
    }])
    fontes_df = pd.DataFrame(fontes_linhas)
    resultados_df = pd.DataFrame(resultados)
    checklist_df = pd.DataFrame(conformidade.get("checklist", []))
    alertas_df = pd.DataFrame({"Alertas": conformidade.get("alertas", [])})
    criterios_df = pd.DataFrame([{
        "descricao_sugerida_licitacon": criterios.get("descricao_sugerida_licitacon", ""),
        "descricao_resumida": criterios.get("descricao_resumida", ""),
        "termos_obrigatorios": ", ".join(criterios.get("termos_obrigatorios", [])),
        "termos_importantes": ", ".join(criterios.get("termos_importantes", [])),
        "frases_chave": ", ".join(criterios.get("frases_chave", [])),
    }])

    aproveitados = fontes_df.copy()
    descartados = pd.DataFrame()
    if not fontes_df.empty and "valor_unitario" in fontes_df:
        valores_aproveitados = set(conformidade.get("precos_aproveitados_lista", []))
        valores_descartados = set(conformidade.get("precos_descartados_lista", []))
        aproveitados = fontes_df[fontes_df["valor_unitario"].isin(valores_aproveitados)]
        descartados = fontes_df[fontes_df["valor_unitario"].isin(valores_descartados)]

    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)
        fontes_df.to_excel(writer, sheet_name="Fontes consultadas", index=False)
        aproveitados.to_excel(writer, sheet_name="Precos aproveitados", index=False)
        descartados.to_excel(writer, sheet_name="Precos descartados", index=False)
        resultados_df.to_excel(writer, sheet_name="Resultados brutos", index=False)
        checklist_df.to_excel(writer, sheet_name="Checklist decreto", index=False)
        alertas_df.to_excel(writer, sheet_name="Alertas", index=False)
        criterios_df.to_excel(writer, sheet_name="Memoria de busca", index=False)

    return saida.getvalue()


def gerar_html_para_download(descricao_busca, qtd_min, qtd_max, criterios, resultados):
    agora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_item = normalizar(
        criterios.get("descricao_sugerida_licitacon", "pesquisa")
    ).replace(" ", "_")[:40]

    nome_base = f"LICITACON_{nome_item}_{agora}"

    pasta_atual = os.getcwd()

    with tempfile.TemporaryDirectory() as pasta_temp:
        os.chdir(pasta_temp)

        nome_html = salvar_html(
            descricao_busca=descricao_busca,
            qtd_min=qtd_min,
            qtd_max=qtd_max,
            criterios=criterios,
            resultados=resultados,
            nome_base=nome_base
        )

        caminho_html = Path(pasta_temp) / nome_html
        conteudo = caminho_html.read_bytes()

        os.chdir(pasta_atual)

    return f"{nome_base}.html", conteudo


def cor_modo(modo):
    if modo == "rigido":
        return "Rigida"
    if modo == "relaxado":
        return "Relaxada"
    if modo == "amplo":
        return "Ampla"
    return modo


def montar_texto_copia(resultado, descricao_link):
    return (
        f"Fonte: {resultado.get('fonte_base', '')}\n"
        f"Municipio fonte: {resultado.get('municipio_fonte', '')}\n"
        f"Orgao: {resultado.get('orgao', '')}\n"
        f"Licitacao: {resultado.get('nr', '')}/{resultado.get('ano', '')}\n"
        f"Descricao para consulta no LicitaCon: {descricao_link}\n"
        f"Descricao encontrada: {resultado.get('descricao', '')}\n"
        f"Quantidade: {resultado.get('qtd', '')}\n"
        f"Unidade: {resultado.get('unidade', '')}\n"
        f"Valor unitario: {resultado.get('valor_unitario', '')}\n"
        f"Valor total: {resultado.get('valor_total', '')}\n"
        f"Modalidade: {resultado.get('modalidade', '')}\n"
        f"Data: {resultado.get('data', '')}\n"
        f"Data homologacao: {resultado.get('data_homologacao', '')}\n"
        f"Vencedor: {resultado.get('vencedor', '')}\n"
        f"CPF/CNPJ: {resultado.get('cpf_cnpj', '')}\n"
        f"Link LicitaCon: {resultado.get('link_licitacon', '')}\n"
        f"Linha CSV: {resultado.get('linha_csv', '')}"
    )


def componente_copiar(texto, chave, rotulo="Copiar dados do resultado"):
    texto_seguro = escape(texto).replace("\n", "&#10;")
    html = f"""
    <div style="margin-top: 6px; margin-bottom: 8px;">
        <textarea id="txt_{chave}" style="position:absolute; left:-9999px;">{texto_seguro}</textarea>
        <button
            onclick="
                var texto = document.getElementById('txt_{chave}').value;
                navigator.clipboard.writeText(texto).then(function() {{
                    var aviso = document.getElementById('aviso_{chave}');
                    aviso.innerText = 'Copiado!';
                    setTimeout(function() {{ aviso.innerText = ''; }}, 1400);
                }});
            "
            style="
                background:#1f6feb;
                color:white;
                border:none;
                padding:8px 12px;
                border-radius:8px;
                font-weight:700;
                cursor:pointer;
                margin-right:8px;
            "
        >
            {escape(rotulo)}
        </button>
        <span id="aviso_{chave}" style="font-weight:700; color:#22c55e;"></span>
    </div>
    """
    components.html(html, height=48)


def componente_copiar_texto_curto(texto, chave, rotulo):
    texto_seguro = escape(str(texto)).replace("\n", " ")
    html = f"""
    <div style="display:inline-block; margin-right:8px; margin-bottom:8px;">
        <textarea id="txt_{chave}" style="position:absolute; left:-9999px;">{texto_seguro}</textarea>
        <button
            onclick="
                var texto = document.getElementById('txt_{chave}').value;
                navigator.clipboard.writeText(texto).then(function() {{
                    var aviso = document.getElementById('aviso_{chave}');
                    aviso.innerText = 'Copiado';
                    setTimeout(function() {{ aviso.innerText = ''; }}, 1200);
                }});
            "
            style="
                background:#eef2ff;
                color:#1e40af;
                border:1px solid #c7d2fe;
                padding:6px 10px;
                border-radius:8px;
                font-weight:700;
                cursor:pointer;
            "
        >
            {escape(rotulo)}
        </button>
        <span id="aviso_{chave}" style="font-size:12px; font-weight:700; color:#22c55e; margin-left:4px;"></span>
    </div>
    """
    components.html(html, height=44)


def exibir_resultado_card(indice, resultado, descricao_link):
    score = resultado.get("score", 0)
    modo = resultado.get("modo_busca", "")
    quantidade_fora = resultado.get("quantidade_fora", False)
    avisos = resultado.get("avisos_tecnicos", "")

    with st.container(border=True):
        col1, col2, col3 = st.columns([1, 1, 2])

        with col1:
            st.metric("Compatibilidade", f"{score}%")

        with col2:
            st.write("**Tipo de busca**")
            st.write(cor_modo(modo))

        with col3:
            if quantidade_fora:
                st.warning("Quantidade fora da faixa informada.")
            if modo == "amplo":
                st.warning("Busca ampla: conferir manualmente antes de usar como referencia.")
            if avisos:
                st.error(f"Aviso tecnico: {avisos}")

        st.write(f"### Resultado {indice}")
        fonte_base = resultado.get("fonte_base", "")
        municipio_fonte = resultado.get("municipio_fonte", "")
        grupo_regional = resultado.get("grupo_regional", "")

        if fonte_base:
            complemento = municipio_fonte or fonte_base
            if grupo_regional:
                complemento = f"{complemento} / {grupo_regional}"
            st.caption(f"Fonte: {complemento}")

        st.write(resultado.get("descricao", ""))

        col_a, col_b, col_c, col_d = st.columns(4)

        with col_a:
            st.write("**Orgao**")
            st.write(resultado.get("orgao", ""))

        with col_b:
            st.write("**Licitacao**")
            nr = resultado.get("nr", "")
            ano = resultado.get("ano", "")
            st.write(f"{nr}/{ano}")

        with col_c:
            st.write("**Quantidade**")
            st.write(resultado.get("qtd", ""))

        with col_d:
            st.write("**Valor unitario**")
            st.write(resultado.get("valor_unitario", ""))

        st.write("**Acoes rapidas**")

        col_link, col_copy = st.columns([1, 3])

        with col_link:
            link_licitacon = resultado.get("link_licitacon") or LINK_BASE_LICITACON
            st.link_button(
                "Abrir LicitaCon",
                link_licitacon,
                use_container_width=True
            )

        with col_copy:
            texto_copia = montar_texto_copia(resultado, descricao_link)
            componente_copiar(
                texto=texto_copia,
                chave=f"geral_{indice}",
                rotulo="Copiar tudo"
            )

        componente_copiar_texto_curto(
            texto=resultado.get("orgao", ""),
            chave=f"orgao_{indice}",
            rotulo="Copiar orgao"
        )

        componente_copiar_texto_curto(
            texto=descricao_link,
            chave=f"desc_link_{indice}",
            rotulo="Copiar descricao para LicitaCon"
        )

        componente_copiar_texto_curto(
            texto=resultado.get("descricao", ""),
            chave=f"desc_resultado_{indice}",
            rotulo="Copiar descricao encontrada"
        )

        componente_copiar_texto_curto(
            texto=resultado.get("valor_unitario", ""),
            chave=f"valor_{indice}",
            rotulo="Copiar valor"
        )

        with st.expander("Ver detalhes adicionais"):
            st.write("**Descricao encontrada no CSV:**")
            st.info(resultado.get("descricao", ""))

            st.write(f"**Modalidade:** {resultado.get('modalidade', '')}")
            st.write(f"**Objeto:** {resultado.get('objeto', '')}")
            st.write(f"**Valor total:** {resultado.get('valor_total', '')}")
            st.write(f"**Data:** {resultado.get('data', '')}")
            st.write(f"**Data homologacao:** {resultado.get('data_homologacao', '')}")
            st.write(f"**Vencedor:** {resultado.get('vencedor', '')}")
            st.write(f"**CPF/CNPJ:** {resultado.get('cpf_cnpj', '')}")
            st.write(f"**Fonte:** {resultado.get('fonte_base', '')}")
            st.write(f"**Municipio fonte:** {resultado.get('municipio_fonte', '')}")
            st.write(f"**Grupo regional:** {resultado.get('grupo_regional', '')}")
            st.write(f"**Link LicitaCon:** {resultado.get('link_licitacon', '')}")
            st.write(f"**Linha no CSV:** {resultado.get('linha_csv', '')}")


# ============================================================
# LAYOUT
# ============================================================

st.title("Pesquisa Inteligente de Precos - LicitaCon/TCE-RS")

st.caption(
    "Interface web para executar a pesquisa automatizada a partir da base local ou CSV do LicitaCon, "
    "mantendo busca rigida, relaxada, ampla, score, validacao tecnica e geracao de HTML."
)

with st.expander("Cadastro de fornecedores especializados"):
    fornecedores_atuais = listar_fornecedores()
    st.caption("Cadastre fornecedores para apoiar cotacoes diretas previstas no perfil normativo da pesquisa.")

    with st.form("form_fornecedor", clear_on_submit=True):
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            novo_nome = st.text_input("Nome / razao social")
            novo_cnpj = st.text_input("CPF/CNPJ")
            novo_email = st.text_input("E-mail")
            novo_telefone = st.text_input("Telefone")
        with col_f2:
            novo_municipio = st.text_input("Municipio")
            novo_uf = st.text_input("UF", value="RS")
            novas_categorias = st.text_input("Categorias atendidas")
            novas_obs = st.text_area("Observacoes", height=80)

        salvar_fornecedor_btn = st.form_submit_button("Salvar fornecedor")
        if salvar_fornecedor_btn:
            if not novo_nome.strip():
                st.error("Informe o nome do fornecedor.")
            else:
                cadastrar_fornecedor({
                    "nome": novo_nome,
                    "cpf_cnpj": novo_cnpj,
                    "email": novo_email,
                    "telefone": novo_telefone,
                    "municipio": novo_municipio,
                    "uf": novo_uf,
                    "categorias": novas_categorias,
                    "observacoes": novas_obs,
                })
                st.success("Fornecedor cadastrado.")
                st.rerun()

    if fornecedores_atuais:
        st.dataframe(pd.DataFrame(fornecedores_atuais), use_container_width=True, hide_index=True)

        with st.form("form_cotacao", clear_on_submit=True):
            st.write("Registrar cotacao recebida")
            fornecedor_opcoes = {
                f"{f['nome']} - {f.get('cpf_cnpj', '')}": f["id"]
                for f in fornecedores_atuais
            }
            fornecedor_label = st.selectbox("Fornecedor", list(fornecedor_opcoes))
            item_cotado = st.text_area("Item pesquisado", height=80)
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                data_solicitacao = st.text_input("Data solicitacao", value=datetime.now().strftime("%Y-%m-%d"))
                valor_unitario_cotado = st.text_input("Valor unitario")
            with col_c2:
                data_resposta = st.text_input("Data resposta", value=datetime.now().strftime("%Y-%m-%d"))
                valor_total_cotado = st.text_input("Valor total")
            with col_c3:
                quantidade_cotada = st.text_input("Quantidade")
                unidade_cotada = st.text_input("Unidade")
            evidencia_cotacao = st.text_area("Evidencia / observacao", height=80)
            status_cotacao = st.selectbox("Status", ["respondida", "solicitada", "sem resposta"])

            salvar_cotacao_btn = st.form_submit_button("Salvar cotacao")
            if salvar_cotacao_btn:
                if not item_cotado.strip():
                    st.error("Informe o item cotado.")
                else:
                    cadastrar_cotacao({
                        "fornecedor_id": fornecedor_opcoes[fornecedor_label],
                        "item_pesquisado": item_cotado,
                        "data_solicitacao": data_solicitacao,
                        "data_resposta": data_resposta,
                        "valor_unitario": converter_numero(valor_unitario_cotado),
                        "valor_total": converter_numero(valor_total_cotado),
                        "quantidade": converter_numero(quantidade_cotada),
                        "unidade": unidade_cotada,
                        "evidencia": evidencia_cotacao,
                        "status": status_cotacao,
                    })
                    st.success("Cotacao registrada.")
                    st.rerun()
    else:
        st.info("Nenhum fornecedor cadastrado ainda.")

with st.sidebar:
    st.header("Fonte de dados")
    sqlite_ok, sqlite_msg = base_sqlite_disponivel()
    opcoes_fonte = ["Base LicitaCon local", "CSV manual"] if sqlite_ok else ["CSV manual"]

    fonte_dados = st.radio(
        "Escolha onde pesquisar",
        opcoes_fonte,
        index=0
    )

    arquivo_csv = None

    if fonte_dados == "Base LicitaCon local":
        st.success("Base local encontrada: licitacon.sqlite")
    else:
        if not sqlite_ok:
            st.warning(sqlite_msg)

        arquivo_csv = st.file_uploader(
            "Selecione o CSV exportado do LicitaCon",
            type=["csv"]
        )

    st.divider()

    st.header("Fontes da pesquisa")
    arquivo_decreto = st.file_uploader(
        "Enviar decreto municipal",
        type=["pdf", "txt"],
        help="O sistema tenta extrair prazo, minimo de precos e base legal. Revise antes de usar."
    )

    if arquivo_decreto is not None:
        texto_decreto = extrair_texto_normativo(
            arquivo_decreto.name,
            arquivo_decreto.getvalue()
        )

        if not texto_decreto.strip():
            st.warning("Nao consegui extrair texto do decreto enviado. Tente enviar em PDF com texto selecionavel ou TXT.")
        else:
            perfil_sugerido = inferir_perfil_decreto(arquivo_decreto.name, texto_decreto)

            with st.expander("Revisar perfil sugerido pelo decreto", expanded=True):
                nome_perfil_upload = st.text_input(
                    "Nome do perfil",
                    value=perfil_sugerido.nome,
                    key="nome_perfil_upload"
                )
                prazo_upload = st.number_input(
                    "Prazo dos precos em dias",
                    min_value=1,
                    max_value=2000,
                    value=int(perfil_sugerido.prazo_precos_dias),
                    step=1,
                    key="prazo_perfil_upload"
                )
                minimo_upload = st.number_input(
                    "Minimo de precos",
                    min_value=1,
                    max_value=20,
                    value=int(perfil_sugerido.minimo_precos),
                    step=1,
                    key="minimo_perfil_upload"
                )
                base_legal_upload = st.text_area(
                    "Base legal",
                    value="\n".join(perfil_sugerido.base_legal),
                    height=90,
                    key="base_perfil_upload"
                )
                observacoes_upload = st.text_area(
                    "Observacoes do perfil",
                    value=perfil_sugerido.observacoes,
                    height=90,
                    key="obs_perfil_upload"
                )

                if st.button("Usar decreto enviado como perfil", use_container_width=True):
                    perfil_custom = type(perfil_sugerido)(
                        codigo=perfil_sugerido.codigo,
                        nome=nome_perfil_upload.strip() or perfil_sugerido.nome,
                        base_legal=tuple(
                            linha.strip()
                            for linha in base_legal_upload.splitlines()
                            if linha.strip()
                        ),
                        prazo_precos_dias=int(prazo_upload),
                        minimo_precos=int(minimo_upload),
                        permite_menos_tres_com_justificativa=True,
                        exige_evidencias=True,
                        observacoes=observacoes_upload.strip(),
                    )
                    registrar_perfil_normativo(perfil_custom)
                    st.session_state["perfil_normativo_upload"] = perfil_para_dict(perfil_custom)
                    st.session_state["perfil_normativo_preferido"] = perfil_custom.codigo
                    st.success("Perfil normativo criado a partir do decreto enviado.")
                    st.rerun()

    perfis_normativos = listar_perfis_normativos()
    mapa_perfis = {perfil.nome: perfil.codigo for perfil in perfis_normativos}
    perfil_preferido = st.session_state.get("perfil_normativo_preferido", "joia_rs_5337")
    nomes_perfis = list(mapa_perfis)
    indice_perfil = 0
    for indice, nome in enumerate(nomes_perfis):
        if mapa_perfis[nome] == perfil_preferido:
            indice_perfil = indice
            break
    perfil_normativo_nome = st.selectbox(
        "Perfil normativo",
        nomes_perfis,
        index=indice_perfil,
        help="Define quais regras legais e prazos serao usados no dossie da pesquisa."
    )
    perfil_normativo_codigo = mapa_perfis[perfil_normativo_nome]

    st.divider()

    st.link_button("Abrir LicitaCon", LINK_BASE_LICITACON, use_container_width=True)

    st.info(
        "Observacao: o LicitaCon nao permite limpar sessao por URL. "
        "Quando abrir o sistema, clique manualmente em Limpar dentro do portal."
    )

st.subheader("Pesquisa por planilha")
st.caption(
    "Envie o termo de referencia para montar uma cesta de precos item por item. "
    "Excel e o formato mais confiavel; Word e PDF podem exigir revisao dos itens extraidos."
)

st.markdown("#### Dados da pesquisa e metodologia")
opcoes_fontes = ["LicitaCon", "PNCP", "Internet", "Fornecedores"]

col_fontes, col_responsavel, col_metodo = st.columns([1.25, 1, 0.85])
with col_fontes:
    fontes_selecionadas = st.multiselect(
        "Bases para consultar",
        opcoes_fontes,
        default=["LicitaCon"],
        help="Internet exige SERPAPI_KEY ou BING_SEARCH_KEY configurada no ambiente."
    )
with col_responsavel:
    responsavel_pesquisa = st.text_input(
        "Responsavel pela pesquisa",
        value="",
        placeholder="Nome do servidor responsavel"
    )
with col_metodo:
    metodo_preferido = st.selectbox(
        "Metodologia de formacao do preco",
        ["auto", "media", "mediana", "menor"],
        index=0,
        help="Auto sugere media ou mediana conforme variacao dos precos."
    )

with st.expander("Justificativas do processo"):
    justificativa_menos_tres = st.text_area(
        "Justificativa para menos de 3 precos",
        height=80,
        key="just_menos_tres"
    )
    justificativa_descartes = st.text_area(
        "Justificativa para descartar valores",
        height=80,
        key="just_descartes"
    )
    justificativa_metodologia = st.text_area(
        "Justificativa da metodologia",
        height=80,
        key="just_metodologia"
    )

st.divider()

col_planilha, col_parametros_lote = st.columns([2, 1])

with col_planilha:
    arquivo_planilha = st.file_uploader(
        "Arquivo do termo de referencia",
        type=["xlsx", "docx", "pdf"],
        key="arquivo_planilha_lote"
    )

with col_parametros_lote:
    max_itens_lote = st.number_input(
        "Limite de itens para testar",
        min_value=1,
        max_value=500,
        value=10,
        step=1,
        help="Para a primeira rodada, teste poucos itens. Depois aumente para a planilha inteira."
    )
    faixa_qtd_lote = st.slider(
        "Faixa aceita em relacao a quantidade da planilha",
        min_value=0,
        max_value=100,
        value=30,
        step=5,
        help="Exemplo: se a planilha pede 100 unidades e a tolerancia e 30%, o sistema pesquisa compras entre 70 e 130 unidades."
    )
    modo_fontes_lote = st.selectbox(
        "Consulta de fontes no lote",
        [
            "Rapida: PNCP/Internet so se faltar preco",
            "Completa: consultar todas em todos os itens",
        ],
        index=0,
        help="O modo rapido evita travar planilhas grandes consultando PNCP em itens que ja tem pelo menos 3 precos no LicitaCon."
    )

executar_lote = st.button(
    "Gerar cesta de precos da planilha",
    type="primary",
    use_container_width=True
)

if executar_lote:
    if "LicitaCon" in fontes_selecionadas and not sqlite_ok:
        st.error(sqlite_msg)
        st.stop()

    if arquivo_planilha is None:
        st.error("Selecione um arquivo XLSX, DOCX ou PDF.")
        st.stop()

    if not responsavel_pesquisa.strip():
        st.error("Informe o responsavel pela pesquisa.")
        st.stop()

    if not fontes_selecionadas:
        st.error("Selecione ao menos uma fonte de pesquisa.")
        st.stop()

    try:
        itens_lote = carregar_itens_documento(arquivo_planilha)
    except Exception as erro:
        st.error(f"Nao foi possivel ler o arquivo do termo de referencia: {erro}")
        st.stop()

    if itens_lote.empty:
        st.error("Nao encontrei itens validos no arquivo enviado.")
        st.stop()

    itens_lote = itens_lote.head(int(max_itens_lote)).copy()
    st.info(f"Processando {len(itens_lote)} item(ns) da planilha.")

    with st.expander("Itens extraidos do termo de referencia", expanded=not arquivo_planilha.name.lower().endswith(".xlsx")):
        st.dataframe(itens_lote, use_container_width=True, hide_index=True)

    justificativas = {
        "menos_tres": justificativa_menos_tres,
        "descartes": justificativa_descartes,
        "metodologia": justificativa_metodologia,
    }

    resumo_lote, detalhes_lote, avisos_lote = montar_linhas_cesta(
        itens_lote,
        qtd_faixa_padrao=faixa_qtd_lote / 100,
        fontes_selecionadas=fontes_selecionadas,
        perfil_codigo=perfil_normativo_codigo,
        responsavel=responsavel_pesquisa.strip(),
        metodo_preferido=metodo_preferido,
        justificativas=justificativas,
        consultar_fontes_adicionais_todos=modo_fontes_lote.startswith("Completa"),
    )
    excel_lote = gerar_excel_cesta(resumo_lote, detalhes_lote)
    pdf_lote = gerar_pdf_cesta(
        resumo_lote,
        detalhes_lote,
        responsavel=responsavel_pesquisa.strip(),
        metodo=metodo_preferido,
        perfil_nome=obter_perfil_normativo(perfil_normativo_codigo).nome,
        fontes_selecionadas=fontes_selecionadas,
    )

    st.session_state["lote_resumo"] = resumo_lote
    st.session_state["lote_detalhes"] = detalhes_lote
    st.session_state["lote_excel"] = excel_lote
    st.session_state["lote_pdf"] = pdf_lote
    st.session_state["lote_avisos"] = avisos_lote
    st.session_state["lote_fontes_selecionadas"] = fontes_selecionadas

st.divider()
st.subheader("Pesquisa individual")

descricao_busca = st.text_area(
    "Descricao do item a pesquisar",
    height=150,
    placeholder="Cole aqui a descricao completa do item..."
)

col_qtd_individual_min, col_qtd_individual_max = st.columns(2)
with col_qtd_individual_min:
    qtd_min_txt = st.text_input(
        "Quantidade minima",
        value="",
        key="qtd_min_individual",
        help="Usada somente na pesquisa individual. Na pesquisa por planilha, cada item usa a quantidade da propria planilha."
    )
with col_qtd_individual_max:
    qtd_max_txt = st.text_input(
        "Quantidade maxima",
        value="",
        key="qtd_max_individual",
        help="Usada somente na pesquisa individual. Na pesquisa por planilha, ajuste a tolerancia de quantidade."
    )

executar = st.button("Executar pesquisa", type="primary", use_container_width=True)

if executar:
    if "LicitaCon" in fontes_selecionadas and fonte_dados == "CSV manual" and arquivo_csv is None:
        st.error("Selecione um arquivo CSV do LicitaCon.")
        st.stop()

    if not descricao_busca.strip():
        st.error("Informe a descricao do item.")
        st.stop()

    if not responsavel_pesquisa.strip():
        st.error("Informe o responsavel pela pesquisa.")
        st.stop()

    if not fontes_selecionadas:
        st.error("Selecione ao menos uma fonte de pesquisa.")
        st.stop()

    qtd_min = converter_numero(qtd_min_txt)
    qtd_max = converter_numero(qtd_max_txt)

    if qtd_min is None or qtd_max is None:
        st.error("Quantidade minima ou maxima invalida.")
        st.stop()

    if qtd_min > qtd_max:
        st.error("Quantidade minima nao pode ser maior que a quantidade maxima.")
        st.stop()

    resultados = []
    estatisticas = {
        "fonte_dados": "Fontes combinadas",
        "avisos_integracao": [],
    }
    criterios = extrair_criterios_com_ia(descricao_busca.strip())

    if "LicitaCon" in fontes_selecionadas:
        if fonte_dados == "Base LicitaCon local":
            if not sqlite_ok:
                st.error(sqlite_msg)
                st.stop()

            with st.spinner("Pesquisando na base local LicitaCon..."):
                criterios, resultados, estatisticas_licitacon = executar_pesquisa_sqlite(
                    descricao_busca=descricao_busca.strip(),
                    qtd_min=qtd_min,
                    qtd_max=qtd_max
                )
            estatisticas.update(estatisticas_licitacon)
            estatisticas["fonte_dados"] = "Fontes combinadas"
            estatisticas["linhas_csv"] = estatisticas_licitacon.get("candidatos_sqlite", 0)
        else:
            with st.spinner("Carregando CSV..."):
                df = carregar_csv(arquivo_csv)

            if df is None or df.empty:
                st.error("Nao foi possivel carregar o CSV ou o arquivo esta vazio.")
                st.stop()

            st.success(f"CSV carregado com {len(df)} linhas.")

            with st.spinner("Analisando descricao com IA e executando buscas no CSV..."):
                criterios, resultados, estatisticas_csv = executar_pesquisa(
                    df=df,
                    descricao_busca=descricao_busca.strip(),
                    qtd_min=qtd_min,
                    qtd_max=qtd_max,
                    criterios=criterios
                )
            estatisticas.update(estatisticas_csv)
            estatisticas["fonte_dados"] = "Fontes combinadas"
            estatisticas["linhas_csv"] = len(df)

    fontes_normalizadas = fontes_de_resultados_licitacon(resultados)

    with st.spinner("Consultando fontes adicionais..."):
        adicionais, avisos_integracao = executar_fontes_adicionais(
            descricao_busca=descricao_busca.strip(),
            fontes_selecionadas=fontes_selecionadas
        )

    fontes_normalizadas.extend(adicionais)
    resultados = resultados + resultados_de_fontes(adicionais)
    estatisticas["avisos_integracao"] = avisos_integracao
    estatisticas["fontes_selecionadas"] = fontes_selecionadas
    estatisticas["fontes_normalizadas"] = fontes_normalizadas
    estatisticas["total_resultados"] = len(resultados)
    estatisticas["total"] = len(resultados)

    justificativas = {
        "menos_tres": justificativa_menos_tres,
        "descartes": justificativa_descartes,
        "metodologia": justificativa_metodologia,
    }

    st.session_state["criterios"] = criterios
    st.session_state["resultados"] = resultados
    st.session_state["estatisticas"] = estatisticas
    st.session_state["fontes_normalizadas"] = fontes_normalizadas
    st.session_state["descricao_busca"] = descricao_busca.strip()
    st.session_state["responsavel_pesquisa"] = responsavel_pesquisa.strip()
    st.session_state["qtd_min"] = qtd_min
    st.session_state["qtd_max"] = qtd_max
    st.session_state["linhas_csv"] = estatisticas.get("linhas_csv", 0)
    st.session_state["metodo_preferido"] = metodo_preferido
    st.session_state["perfil_normativo_codigo"] = perfil_normativo_codigo
    st.session_state["justificativas"] = justificativas

if "lote_resumo" in st.session_state:
    st.divider()
    st.subheader("Resumo da cesta de precos")
    resumo_lote = st.session_state["lote_resumo"]
    detalhes_lote = st.session_state["lote_detalhes"]

    col_ok, col_atencao, col_revisar, col_sem = st.columns(4)
    col_ok.metric("OK", int((resumo_lote["Status"] == "OK").sum()))
    col_atencao.metric("Atencao", int((resumo_lote["Status"] == "Atencao").sum()))
    col_revisar.metric("Revisar", int((resumo_lote["Status"] == "Revisar").sum()))
    col_sem.metric("Sem resultado", int((resumo_lote["Status"] == "Sem resultado").sum()))

    st.dataframe(resumo_lote, use_container_width=True, hide_index=True)

    with st.expander("Precos encontrados por item"):
        st.dataframe(detalhes_lote, use_container_width=True, hide_index=True)

    for aviso in st.session_state.get("lote_avisos", []):
        st.warning(aviso)

    col_pdf_lote, col_excel_lote = st.columns(2)
    with col_pdf_lote:
        st.download_button(
            label="Baixar dossie da pesquisa em PDF",
            data=st.session_state["lote_pdf"],
            file_name=f"dossie_pesquisa_precos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    with col_excel_lote:
        st.download_button(
            label="Baixar base detalhada em Excel",
            data=st.session_state["lote_excel"],
            file_name=f"cesta_de_precos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

if "resultados" in st.session_state:
    criterios = st.session_state["criterios"]
    resultados = st.session_state["resultados"]
    estatisticas = st.session_state["estatisticas"]
    fontes_normalizadas = st.session_state.get("fontes_normalizadas", [])
    justificativas = st.session_state.get("justificativas", {})
    perfil_atual = obter_perfil_normativo(st.session_state.get("perfil_normativo_codigo"))

    descricao_link = criterios.get("descricao_sugerida_licitacon", "")
    if not descricao_link:
        descricao_link = criterios.get("descricao_resumida", st.session_state["descricao_busca"])

    st.divider()

    st.subheader("Resumo da pesquisa")
    st.caption(f"Perfil normativo: {perfil_atual.nome}")

    total_linhas = estatisticas.get("linhas_csv", st.session_state.get("linhas_csv", 0))
    total_resultados = estatisticas.get("total_resultados", estatisticas.get("total", len(resultados)))

    fonte_metric = estatisticas.get("fonte_dados", "CSV")
    rotulo_linhas = "Candidatos analisados" if fonte_metric == "Base LicitaCon local" else "Linhas analisadas no CSV"

    col1, col2, col3 = st.columns(3)
    col1.metric(rotulo_linhas, total_linhas)
    col2.metric("Resultados compativeis encontrados", total_resultados)
    col3.metric("Fontes normalizadas", len(fontes_normalizadas))

    for aviso in estatisticas.get("avisos_integracao", []):
        st.warning(aviso)

    if estatisticas.get("resultados_regionais", 0):
        st.info(
            "A pesquisa geral trouxe poucos resultados, entao o sistema complementou "
            "com a base historica dos municipios regionais."
        )

    if (
        estatisticas.get("usou_criterios_ampliados", False)
        or estatisticas.get("amplo", 0) > 0
        or estatisticas.get("amplo_sem_qtd", 0) > 0
        or estatisticas.get("relaxado_sem_qtd", 0) > 0
    ):
        st.warning(
            "Foram utilizados criterios ampliados para complementar os resultados. "
            "Recomenda-se conferencia manual dos itens antes de utilizar como referencia de preco."
        )

    with st.expander("Criterios extraidos"):
        st.write("**Descricao sugerida para pesquisar no LicitaCon:**")
        st.code(descricao_link)

        componente_copiar_texto_curto(
            texto=descricao_link,
            chave="descricao_sugerida_resumo",
            rotulo="Copiar descricao sugerida"
        )

        st.write("**Termos obrigatorios:**")
        st.write(", ".join(criterios.get("termos_obrigatorios", [])) or "-")

        st.write("**Termos importantes:**")
        st.write(", ".join(criterios.get("termos_importantes", [])) or "-")

        st.write("**Frases-chave:**")
        st.write(", ".join(criterios.get("frases_chave", [])) or "-")

    if not resultados:
        st.error("Nenhum resultado encontrado.")
    else:
        conformidade = avaliar_conformidade_pesquisa(
            fontes_normalizadas or resultados,
            descricao_objeto=st.session_state["descricao_busca"],
            responsavel=st.session_state.get("responsavel_pesquisa", ""),
            justificativa_menos_tres=justificativas.get("menos_tres", ""),
            justificativa_descartes=justificativas.get("descartes", ""),
            metodo_preferido=st.session_state.get("metodo_preferido", "auto"),
            perfil_codigo=st.session_state.get("perfil_normativo_codigo", "joia_rs_5337"),
        )

        st.subheader("Conformidade normativa")
        st.caption(
            f"Resumo automatico para apoiar a formalizacao da pesquisa conforme {conformidade.get('perfil_normativo', '')}."
        )

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Precos validos", conformidade["total_precos"])
        col_b.metric("Dentro do prazo", conformidade.get("precos_no_prazo", conformidade["precos_no_prazo_6_meses"]))
        col_c.metric("Precos aproveitados", conformidade["precos_aproveitados"])
        col_d.metric("Descartados por faixa", conformidade["precos_descartados"])

        col_e, col_f, col_g, col_h = st.columns(4)
        col_e.metric("Menor", formatar_moeda(conformidade["menor"]))
        col_f.metric("Media", formatar_moeda(conformidade["media"]))
        col_g.metric("Mediana", formatar_moeda(conformidade["mediana"]))
        col_h.metric("Valor sugerido", formatar_moeda(conformidade["valor_sugerido"]))

        if conformidade["metodo_sugerido"]:
            st.info(f"Metodo sugerido: {conformidade['metodo_sugerido']}.")

        for alerta in conformidade["alertas"]:
            st.warning(alerta)

        if conformidade.get("justificativas_exigidas"):
            st.error(
                "Justificativas pendentes: "
                + " | ".join(conformidade["justificativas_exigidas"])
            )

        with st.expander("Checklist normativo"):
            checklist_df = pd.DataFrame(conformidade.get("checklist", []))
            if not checklist_df.empty:
                st.dataframe(checklist_df, use_container_width=True, hide_index=True)

        with st.expander("Fontes normalizadas para o dossie"):
            if fontes_normalizadas:
                st.dataframe(
                    pd.DataFrame(fontes_para_dataframe_linhas(fontes_normalizadas)),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nenhuma fonte normalizada foi gerada.")

        with st.expander("Base normativa considerada"):
            for base in conformidade.get("base_legal", []):
                st.write(f"- {base}")
            st.write(f"Prazo de referencia configurado: {conformidade.get('prazo_precos_dias', '')} dias.")
            st.write(f"Minimo de precos configurado: {conformidade.get('minimo_precos', '')}.")
            st.write(perfil_atual.observacoes)

        st.subheader("Resultados encontrados")

        qtd_exibir = st.slider(
            "Quantidade de resultados para exibir na tela",
            min_value=1,
            max_value=min(len(resultados), 80),
            value=min(len(resultados), 20)
        )

        for i, resultado in enumerate(resultados[:qtd_exibir], start=1):
            exibir_resultado_card(i, resultado, descricao_link)

        nome_html, conteudo_html = gerar_html_para_download(
            descricao_busca=st.session_state["descricao_busca"],
            qtd_min=st.session_state["qtd_min"],
            qtd_max=st.session_state["qtd_max"],
            criterios=criterios,
            resultados=resultados
        )

        st.download_button(
            label="Baixar HTML completo da pesquisa",
            data=conteudo_html,
            file_name=nome_html,
            mime="text/html",
            use_container_width=True
        )

        dossie_excel = gerar_excel_dossie(
            descricao_busca=st.session_state["descricao_busca"],
            responsavel=st.session_state.get("responsavel_pesquisa", ""),
            criterios=criterios,
            resultados=resultados,
            fontes=fontes_normalizadas,
            conformidade=conformidade,
            justificativas=justificativas,
        )

        st.download_button(
            label="Baixar dossie da pesquisa em Excel",
            data=dossie_excel,
            file_name=f"dossie_pesquisa_precos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        if st.button("Registrar pesquisa no banco local", use_container_width=True):
            pesquisa_id = salvar_pesquisa(
                descricao=st.session_state["descricao_busca"],
                responsavel=st.session_state.get("responsavel_pesquisa", ""),
                parametros=json.dumps({
                    "qtd_min": st.session_state["qtd_min"],
                    "qtd_max": st.session_state["qtd_max"],
                    "fontes": estatisticas.get("fontes_selecionadas", []),
                    "perfil_normativo": st.session_state.get("perfil_normativo_codigo"),
                }, ensure_ascii=False),
                metodo_escolhido=conformidade.get("metodo_sugerido", ""),
                justificativas=json.dumps(justificativas, ensure_ascii=False),
                fontes=fontes_normalizadas,
            )
            st.success(f"Pesquisa registrada no banco local com ID {pesquisa_id}.")
else:
    st.info("Para pesquisa individual, selecione as fontes, informe a descricao e a faixa de quantidade.")
