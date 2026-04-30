import os
import re
import sqlite3
import tempfile
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
from conformidade_joia import avaliar_conformidade_pesquisa, formatar_moeda


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


def montar_linhas_cesta(itens_df, qtd_faixa_padrao=0.30, limite_precos_item=5):
    resumo = []
    detalhes = []

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

        try:
            criterios, resultados, estatisticas = executar_pesquisa_sqlite(
                descricao_busca=descricao,
                qtd_min=qtd_min,
                qtd_max=qtd_max,
                limite_candidatos=MAX_CANDIDATOS_LOTE,
            )
            conformidade = avaliar_conformidade_pesquisa(resultados)
            status = classificar_status_lote(conformidade, resultados)
            erro = ""
        except Exception as exc:
            criterios = {}
            resultados = []
            estatisticas = {}
            conformidade = avaliar_conformidade_pesquisa([])
            status = "Erro"
            erro = str(exc)

        resumo.append({
            "Item": item.get("item", posicao),
            "Descricao original": descricao,
            "Quantidade solicitada": quantidade if quantidade is not None else "",
            "Status": status,
            "Resultados encontrados": len(resultados),
            "Precos validos": conformidade["total_precos"],
            "Precos dentro de 6 meses": conformidade["precos_no_prazo_6_meses"],
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
                "Link LicitaCon": resultado.get("link_licitacon", ""),
            })

        barra.progress(posicao / total)

    status_texto.write("Pesquisa por planilha concluida.")
    return pd.DataFrame(resumo), pd.DataFrame(detalhes)


def gerar_excel_cesta(resumo_df, detalhes_df):
    saida = BytesIO()

    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, sheet_name="Resumo", index=False)
        detalhes_df.to_excel(writer, sheet_name="Precos encontrados", index=False)

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

    st.header("Parametros")
    qtd_min_txt = st.text_input("Quantidade minima", value="")
    qtd_max_txt = st.text_input("Quantidade maxima", value="")

    st.divider()

    st.link_button("Abrir LicitaCon", LINK_BASE_LICITACON, use_container_width=True)

    st.info(
        "Observacao: o LicitaCon nao permite limpar sessao por URL. "
        "Quando abrir o sistema, clique manualmente em Limpar dentro do portal."
    )

st.subheader("Pesquisa por planilha")
st.caption(
    "Envie o termo de referencia em Excel para montar uma cesta de precos item por item. "
    "Use primeiro uma amostra pequena para validar os parametros."
)

col_planilha, col_parametros_lote = st.columns([2, 1])

with col_planilha:
    arquivo_planilha = st.file_uploader(
        "Planilha do termo de referencia",
        type=["xlsx"],
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
        "Tolerancia de quantidade",
        min_value=0,
        max_value=100,
        value=30,
        step=5,
        help="Exemplo: 30% aceita licitacoes com quantidade um pouco menor ou maior que a solicitada."
    )

executar_lote = st.button(
    "Gerar cesta de precos da planilha",
    type="primary",
    use_container_width=True
)

if executar_lote:
    if not sqlite_ok:
        st.error(sqlite_msg)
        st.stop()

    if arquivo_planilha is None:
        st.error("Selecione uma planilha XLSX.")
        st.stop()

    try:
        itens_lote = carregar_planilha_itens(arquivo_planilha)
    except Exception as erro:
        st.error(f"Nao foi possivel ler a planilha: {erro}")
        st.stop()

    if itens_lote.empty:
        st.error("Nao encontrei itens validos na planilha.")
        st.stop()

    itens_lote = itens_lote.head(int(max_itens_lote)).copy()
    st.info(f"Processando {len(itens_lote)} item(ns) da planilha.")

    resumo_lote, detalhes_lote = montar_linhas_cesta(
        itens_lote,
        qtd_faixa_padrao=faixa_qtd_lote / 100,
    )
    excel_lote = gerar_excel_cesta(resumo_lote, detalhes_lote)

    st.session_state["lote_resumo"] = resumo_lote
    st.session_state["lote_detalhes"] = detalhes_lote
    st.session_state["lote_excel"] = excel_lote

if "lote_resumo" in st.session_state:
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

    st.download_button(
        label="Baixar cesta de precos em Excel",
        data=st.session_state["lote_excel"],
        file_name=f"cesta_de_precos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

st.divider()
st.subheader("Pesquisa individual")

descricao_busca = st.text_area(
    "Descricao do item a pesquisar",
    height=150,
    placeholder="Cole aqui a descricao completa do item..."
)

executar = st.button("Executar pesquisa", type="primary", use_container_width=True)

if executar:
    if fonte_dados == "CSV manual" and arquivo_csv is None:
        st.error("Selecione um arquivo CSV do LicitaCon.")
        st.stop()

    if not descricao_busca.strip():
        st.error("Informe a descricao do item.")
        st.stop()

    qtd_min = converter_numero(qtd_min_txt)
    qtd_max = converter_numero(qtd_max_txt)

    if qtd_min is None or qtd_max is None:
        st.error("Quantidade minima ou maxima invalida.")
        st.stop()

    if qtd_min > qtd_max:
        st.error("Quantidade minima nao pode ser maior que a quantidade maxima.")
        st.stop()

    if fonte_dados == "Base LicitaCon local":
        if not sqlite_ok:
            st.error(sqlite_msg)
            st.stop()

        with st.spinner("Pesquisando na base local LicitaCon..."):
            criterios, resultados, estatisticas = executar_pesquisa_sqlite(
                descricao_busca=descricao_busca.strip(),
                qtd_min=qtd_min,
                qtd_max=qtd_max
            )

        st.session_state["criterios"] = criterios
        st.session_state["resultados"] = resultados
        st.session_state["estatisticas"] = estatisticas
        st.session_state["descricao_busca"] = descricao_busca.strip()
        st.session_state["qtd_min"] = qtd_min
        st.session_state["qtd_max"] = qtd_max
        st.session_state["linhas_csv"] = estatisticas.get("candidatos_sqlite", 0)
        st.rerun()
    with st.spinner("Carregando CSV..."):
        df = carregar_csv(arquivo_csv)

    if df is None or df.empty:
        st.error("Nao foi possivel carregar o CSV ou o arquivo esta vazio.")
        st.stop()

    st.success(f"CSV carregado com {len(df)} linhas.")

    with st.spinner("Analisando descricao com IA e executando buscas..."):
        criterios, resultados, estatisticas = executar_pesquisa(
            df=df,
            descricao_busca=descricao_busca.strip(),
            qtd_min=qtd_min,
            qtd_max=qtd_max
        )

    st.session_state["criterios"] = criterios
    st.session_state["resultados"] = resultados
    st.session_state["estatisticas"] = estatisticas
    st.session_state["descricao_busca"] = descricao_busca.strip()
    st.session_state["qtd_min"] = qtd_min
    st.session_state["qtd_max"] = qtd_max
    st.session_state["linhas_csv"] = len(df)

if "resultados" in st.session_state:
    criterios = st.session_state["criterios"]
    resultados = st.session_state["resultados"]
    estatisticas = st.session_state["estatisticas"]

    descricao_link = criterios.get("descricao_sugerida_licitacon", "")
    if not descricao_link:
        descricao_link = criterios.get("descricao_resumida", st.session_state["descricao_busca"])

    st.divider()

    st.subheader("Resumo da pesquisa")

    total_linhas = estatisticas.get("linhas_csv", st.session_state.get("linhas_csv", 0))
    total_resultados = estatisticas.get("total_resultados", estatisticas.get("total", len(resultados)))

    fonte_metric = estatisticas.get("fonte_dados", "CSV")
    rotulo_linhas = "Candidatos analisados" if fonte_metric == "Base LicitaCon local" else "Linhas analisadas no CSV"

    col1, col2, col3 = st.columns(3)
    col1.metric(rotulo_linhas, total_linhas)
    col2.metric("Resultados compativeis encontrados", total_resultados)
    col3.metric("Candidatos regionais analisados", estatisticas.get("candidatos_regionais", 0))

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
        conformidade = avaliar_conformidade_pesquisa(resultados)

        st.subheader("Conformidade com Decreto 5.337/2023")
        st.caption(
            "Resumo automatico para apoiar a formalizacao da pesquisa de precos do Municipio de Joia."
        )

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Precos validos", conformidade["total_precos"])
        col_b.metric("Dentro de 6 meses", conformidade["precos_no_prazo_6_meses"])
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

        with st.expander("Base normativa considerada"):
            st.write(
                "Decreto Municipal 5.337/2023: exige documento com descricao do objeto, "
                "fontes consultadas, serie de precos, metodo estatistico, memoria de calculo "
                "e justificativa para descartar valores inconsistentes, inexequiveis ou excessivos."
            )
            st.write(
                "Para contratacoes similares no LicitaCon, o decreto menciona processos homologados "
                "concluidos no maximo 6 meses antes da pesquisa. Valores mais antigos podem exigir "
                "justificativa e eventual indice de atualizacao."
            )
            st.write(
                "Decreto Municipal 5.531/2024: para Sistema de Registro de Precos, remete a ampla "
                "pesquisa de mercado conforme o Decreto 5.337/2023."
            )

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
else:
    st.info("Selecione a fonte de dados, informe a descricao e as quantidades para iniciar.")
