import re
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
import logging
from pathlib import Path

import pandas as pd

from database.paths import DEFAULT_OPERATIONAL_DB_PATH, DEFAULT_RAW_DB_PATH, path_str
from utils.util import normalizar, palavras_fortes
from search.technical import (
    ATRIBUTOS_FRACOS,
    STOPWORDS_TECNICAS,
    aplicar_sinonimos_tecnicos,
    consulta_generica,
    detectar_categoria_semantica,
    expandir_termos_sinonimos,
    extrair_nucleo_semantico,
    obter_category_profile,
    remover_atributos_fracos_tokens,
    parse_atributos_tecnicos,
    tokens_busca_tecnica,
)


MUNICIPIO_PROPRIO_PADRAO = "Joia"
FTS_BASE_PESQUISA = "base_pesquisa_fts"
TABELA_OPERACIONAL = "base_pesquisa_operacional"
FTS_OPERACIONAL = "base_pesquisa_operacional_fts"
logger = logging.getLogger(__name__)
_CANDIDATOS_CORE_CACHE = OrderedDict()
_CANDIDATOS_CORE_CACHE_MAX = 128


@dataclass(frozen=True)
class TabelaBuscaSQLite:
    rotulo: str
    campos_extras: str


TABELAS_SQLITE_BUSCA = {
    "base_pesquisa": TabelaBuscaSQLite(
        rotulo="LicitaCon geral",
        campos_extras=(
            "'' AS \"Municipio Fonte\", "
            "'' AS \"Grupo Regional\", "
            "'LicitaCon geral' AS \"Fonte Base\""
        ),
    ),
    "base_historica_municipios": TabelaBuscaSQLite(
        rotulo="Historico regional",
        campos_extras=(
            "municipio AS \"Municipio Fonte\", "
            "grupo_regional AS \"Grupo Regional\", "
            "'Historico regional' AS \"Fonte Base\""
        ),
    ),
}


def conectar_licitacon(caminho_sqlite):
    con = sqlite3.connect(Path(caminho_sqlite))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -200000")
    return con


def conectar_licitacon_admin(caminho_sqlite):
    con = sqlite3.connect(Path(caminho_sqlite))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -200000")
    return con


def sqlite_suporta_fts5():
    try:
        with sqlite3.connect(":memory:") as con:
            con.execute("CREATE VIRTUAL TABLE teste_fts USING fts5(texto)")
        return True
    except sqlite3.Error:
        return False


def detectar_tipo_banco(caminho_sqlite):
    caminho = Path(caminho_sqlite)
    if not caminho.exists():
        return None

    with conectar_licitacon(caminho) as con:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (TABELA_OPERACIONAL,),
        ).fetchone():
            return "operational"
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'base_pesquisa'",
        ).fetchone():
            return "raw"
    return None


def base_sqlite_disponivel(caminho_sqlite, tabela="base_pesquisa"):
    caminho = Path(caminho_sqlite)
    if not caminho.exists():
        return False, f"Arquivo da base LicitaCon nao encontrado: {caminho}"

    try:
        with conectar_licitacon(caminho) as con:
            tipo = detectar_tipo_banco(caminho)
            if tipo == "operational":
                con.execute(f"SELECT 1 FROM {TABELA_OPERACIONAL} LIMIT 1").fetchone()
            else:
                con.execute(f"SELECT 1 FROM {validar_tabela(tabela)} LIMIT 1").fetchone()
        return True, ""
    except Exception as erro:
        return False, f"Nao foi possivel abrir a base SQLite: {erro}"


def validar_tabela(tabela):
    if tabela not in TABELAS_SQLITE_BUSCA:
        raise ValueError(f"Tabela de busca nao permitida: {tabela}")
    return tabela


def objeto_sqlite_existe(caminho_sqlite, nome, tipo=None):
    caminho = Path(caminho_sqlite)
    if not caminho.exists():
        return False

    sql = "SELECT 1 FROM sqlite_master WHERE name = ?"
    params = [nome]
    if tipo:
        sql += " AND type = ?"
        params.append(tipo)

    with conectar_licitacon(caminho) as con:
        return con.execute(sql, params).fetchone() is not None


def tabela_sqlite_existe(caminho_sqlite, nome_tabela):
    validar_tabela(nome_tabela)
    caminho = Path(caminho_sqlite)
    if not caminho.exists():
        return False

    with conectar_licitacon(caminho) as con:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (nome_tabela,),
        ).fetchone() is not None


def montar_termos_sqlite(descricao_busca, criterios):
    analise_tecnica = parse_atributos_tecnicos(descricao_busca)
    textos = [
        descricao_busca,
        criterios.get("descricao_sugerida_licitacon", ""),
        criterios.get("descricao_resumida", ""),
        " ".join(criterios.get("termos_obrigatorios", [])),
        " ".join(criterios.get("termos_importantes", [])),
    ]

    termos = []
    termos.extend(tokens_busca_tecnica(descricao_busca))
    termos.extend(analise_tecnica["termos_principais"])

    for texto in textos:
        termos.extend(palavras_fortes(texto))
        termos.extend(
            p.lower()
            for p in re.findall(r"[a-zA-Z]+|\d+(?:[,.]\d+)?[a-zA-Z]*", str(texto), flags=re.UNICODE)
        )

    termos = expandir_termos_sinonimos(termos)
    termos = [
        normalizar(termo) for termo in dict.fromkeys(termos)
        if normalizar(termo)
        and normalizar(termo) not in STOPWORDS_TECNICAS
        and normalizar(termo) not in ATRIBUTOS_FRACOS
        and normalizar(termo) not in {"volts", "horas"}
    ]

    return list(dict.fromkeys(termos))[:14]


def montar_match_fts(termos):
    termos_limpos = []
    for termo in termos:
        termo_norm = normalizar(termo)
        partes = re.findall(r"[a-z0-9_]+", termo_norm)
        termos_limpos.extend(
            parte
            for parte in partes
            if parte.isdigit() or len(parte) >= 2
        )

    termos_unicos = list(dict.fromkeys(termos_limpos))[:10]
    if not termos_unicos:
        return ""

    return " OR ".join(f'"{termo}"*' for termo in termos_unicos)


def montar_matches_fts(descricao_busca, criterios):
    analise = parse_atributos_tecnicos(descricao_busca)
    termos = montar_termos_sqlite(descricao_busca, criterios)
    principais = remover_atributos_fracos_tokens(
        expandir_termos_sinonimos(analise["termos_principais"]),
        contexto="fts_principais",
    )
    atributos = [
        atributo.get("bruto") or atributo.get("valor")
        for atributo in analise["atributos_criticos"].values()
        if atributo.get("bruto") or atributo.get("valor")
    ]
    atributos = remover_atributos_fracos_tokens(
        expandir_termos_sinonimos(atributos),
        contexto="fts_atributos",
    )
    nucleo = extrair_nucleo_semantico(descricao_busca)
    fallback_semantico = remover_atributos_fracos_tokens(
        expandir_termos_sinonimos((nucleo.get("search_core") or "").split()),
        contexto="semantic_fallback",
    )

    consulta_e_generica = consulta_generica(descricao_busca)
    tentativas = [
        ("and_principal_atributos", principais + atributos),
        ("and_principais", principais),
    ]
    if not consulta_e_generica:
        tentativas.extend([
            ("principal_atributos", principais + atributos),
            ("tecnica_completa", termos),
            ("principais", principais),
            ("fortes", termos[:8]),
        ])
    else:
        tentativas.append(("principal_atributos_restrito", principais + atributos))
    if fallback_semantico:
        tentativas.append(("semantic_fallback", fallback_semantico))

    matches = []
    vistos = set()
    for nome, termos_tentativa in tentativas:
        if nome.startswith("and_"):
            partes = []
            for termo in termos_tentativa:
                termo_norm = normalizar(termo)
                pedacos = [
                    parte
                    for parte in re.findall(r"[a-z0-9_]+", termo_norm)
                    if (parte.isdigit() or len(parte) >= 2)
                    and parte not in STOPWORDS_TECNICAS
                    and parte not in ATRIBUTOS_FRACOS
                ]
                partes.extend(pedacos)
            termos_unicos = list(dict.fromkeys(partes))[:5]
            match = " AND ".join(f'"{termo}"*' for termo in termos_unicos)
        else:
            match = montar_match_fts(termos_tentativa)
        if match and match not in vistos:
            matches.append((nome, match))
            vistos.add(match)

    return matches


def _strict_first_deve_parar(nome_estrategia, quantidade, limite, descricao_busca):
    if quantidade <= 0:
        return False
    if nome_estrategia.startswith("and_") and quantidade >= min(limite, 80):
        return True
    if consulta_generica(descricao_busca) and quantidade >= min(limite, 120):
        return True
    return False


def _strict_zero_deve_abortar(nome_estrategia, quantidade, descricao_busca):
    if quantidade > 0 or not nome_estrategia.startswith("and_"):
        return False
    categoria = detectar_categoria_semantica(descricao_busca)
    profile = obter_category_profile(categoria)
    if profile.get("rigidez") != "alta":
        logger.info(
            "[expansao_soft_penalty] categoria=%s motivo=strict_zero_fts acao=continuar_expansao",
            categoria,
        )
        return False
    analise = parse_atributos_tecnicos(descricao_busca)
    termos = analise.get("termos_principais", [])
    atributos = analise.get("atributos_criticos", {})
    if atributos:
        return False
    return len(termos) >= 5 and any(len(termo) >= 8 or any(ch.isdigit() for ch in termo) for termo in termos)


def _filtro_exclusao_municipio(tabela, excluir_municipio):
    if not excluir_municipio:
        return "", []

    variantes_municipio = {
        excluir_municipio.lower(),
        normalizar(excluir_municipio).lower(),
    }
    if normalizar(excluir_municipio) == "joia":
        variantes_municipio.add("joia")
        variantes_municipio.add("jóia")

    colunas_exclusao = ["orgao"]
    if tabela == "base_historica_municipios":
        colunas_exclusao.append("municipio")

    filtros = []
    parametros = []
    for coluna in colunas_exclusao:
        for variante in sorted(variantes_municipio):
            filtros.append(f"lower(COALESCE({coluna}, '')) NOT LIKE ?")
            parametros.append(f"%{variante}%")

    return " AND " + " AND ".join(filtros), parametros


def _registrar_resultado_busca(
    df,
    estrategia,
    tempo_inicio,
    candidatos,
    detalhe="",
    banco="raw",
    caminho="",
    fallback=False,
):
    tempo_ms = round((time.perf_counter() - tempo_inicio) * 1000, 2)
    df.attrs["sqlite_search"] = {
        "estrategia": estrategia,
        "tempo_ms": tempo_ms,
        "candidatos": candidatos,
        "detalhe": detalhe,
        "banco": banco,
        "caminho": str(caminho),
        "fallback": fallback,
    }
    logger.info(
        "SQLite search strategy=%s candidates=%s time_ms=%s detail=%s",
        estrategia,
        candidatos,
        tempo_ms,
        detalhe,
    )
    return df


def _cache_key_candidatos(banco, caminho, descricao_busca, limite, excluir_municipio):
    nucleo = extrair_nucleo_semantico(str(descricao_busca or ""))
    core = nucleo.get("semantic_core")
    if not core or not nucleo.get("tem_variantes"):
        return None, nucleo
    return (
        banco,
        str(Path(caminho)),
        core,
        int(limite),
        normalizar(excluir_municipio or ""),
    ), nucleo


def _obter_cache_candidatos(chave, core):
    if not chave or chave not in _CANDIDATOS_CORE_CACHE:
        return None
    df = _CANDIDATOS_CORE_CACHE.pop(chave)
    _CANDIDATOS_CORE_CACHE[chave] = df
    reutilizado = df.copy(deep=False)
    reutilizado.attrs["sqlite_search"] = dict(df.attrs.get("sqlite_search", {}))
    reutilizado.attrs["sqlite_search"].update({
        "cache_core": True,
        "fts_reutilizado": True,
        "semantic_core": core,
    })
    logger.info(
        "[reuse_candidates] core=%r fts_reutilizado=True candidatos=%s",
        core,
        len(reutilizado),
    )
    logger.info(
        "[cache_core] reutilizado core=%r candidatos=%s",
        core,
        len(reutilizado),
    )
    return reutilizado


def _salvar_cache_candidatos(chave, df, core):
    if not chave or df is None:
        return df
    armazenado = df.copy(deep=False)
    armazenado.attrs["sqlite_search"] = dict(df.attrs.get("sqlite_search", {}))
    armazenado.attrs["sqlite_search"].update({
        "cache_core": True,
        "fts_reutilizado": False,
        "semantic_core": core,
    })
    _CANDIDATOS_CORE_CACHE[chave] = armazenado
    while len(_CANDIDATOS_CORE_CACHE) > _CANDIDATOS_CORE_CACHE_MAX:
        _CANDIDATOS_CORE_CACHE.popitem(last=False)
    df.attrs["sqlite_search"] = dict(armazenado.attrs["sqlite_search"])
    logger.info(
        "[cache_core] salvo core=%r candidatos=%s",
        core,
        len(df),
    )
    return df


def _filtro_exclusao_operacional(excluir_municipio):
    if not excluir_municipio:
        return "", []

    variantes = {
        excluir_municipio.lower(),
        normalizar(excluir_municipio).lower(),
    }
    if normalizar(excluir_municipio) == "joia":
        variantes.add("joia")
        variantes.add("jÃ³ia")

    filtros = []
    params = []
    for coluna in ["orgao", "municipio"]:
        for variante in sorted(variantes):
            filtros.append(f"lower(COALESCE(o.{coluna}, '')) NOT LIKE ?")
            params.append(f"%{variante}%")
    return " AND " + " AND ".join(filtros), params


def sql_criar_fts_base_pesquisa():
    return f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_BASE_PESQUISA}
    USING fts5(
        item,
        objeto,
        orgao,
        modalidade,
        vencedor,
        content='base_pesquisa',
        content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 2'
    );
    """


def sql_criar_triggers_fts_base_pesquisa():
    return f"""
    CREATE TRIGGER IF NOT EXISTS base_pesquisa_fts_ai AFTER INSERT ON base_pesquisa BEGIN
        INSERT INTO {FTS_BASE_PESQUISA}(rowid, item, objeto, orgao, modalidade, vencedor)
        VALUES (new.rowid, new.item, new.objeto, new.orgao, new.modalidade, new.vencedor);
    END;

    CREATE TRIGGER IF NOT EXISTS base_pesquisa_fts_ad AFTER DELETE ON base_pesquisa BEGIN
        INSERT INTO {FTS_BASE_PESQUISA}({FTS_BASE_PESQUISA}, rowid, item, objeto, orgao, modalidade, vencedor)
        VALUES ('delete', old.rowid, old.item, old.objeto, old.orgao, old.modalidade, old.vencedor);
    END;

    CREATE TRIGGER IF NOT EXISTS base_pesquisa_fts_au AFTER UPDATE ON base_pesquisa BEGIN
        INSERT INTO {FTS_BASE_PESQUISA}({FTS_BASE_PESQUISA}, rowid, item, objeto, orgao, modalidade, vencedor)
        VALUES ('delete', old.rowid, old.item, old.objeto, old.orgao, old.modalidade, old.vencedor);
        INSERT INTO {FTS_BASE_PESQUISA}(rowid, item, objeto, orgao, modalidade, vencedor)
        VALUES (new.rowid, new.item, new.objeto, new.orgao, new.modalidade, new.vencedor);
    END;
    """


def criar_indice_fts_base_pesquisa(caminho_sqlite, recriar=False, criar_triggers=True):
    if not sqlite_suporta_fts5():
        return False, "SQLite local nao suporta FTS5."

    with conectar_licitacon_admin(caminho_sqlite) as con:
        if recriar:
            con.executescript(
                f"""
                DROP TRIGGER IF EXISTS base_pesquisa_fts_ai;
                DROP TRIGGER IF EXISTS base_pesquisa_fts_ad;
                DROP TRIGGER IF EXISTS base_pesquisa_fts_au;
                DROP TABLE IF EXISTS {FTS_BASE_PESQUISA};
                """
            )
        con.execute(sql_criar_fts_base_pesquisa())
        if criar_triggers:
            con.executescript(sql_criar_triggers_fts_base_pesquisa())
        con.commit()
    return True, f"Indice FTS5 {FTS_BASE_PESQUISA} criado/verificado."


def reconstruir_indice_fts_base_pesquisa(caminho_sqlite):
    ok, mensagem = criar_indice_fts_base_pesquisa(caminho_sqlite)
    if not ok:
        return False, mensagem

    inicio = time.perf_counter()
    with conectar_licitacon_admin(caminho_sqlite) as con:
        con.execute(f"INSERT INTO {FTS_BASE_PESQUISA}({FTS_BASE_PESQUISA}) VALUES ('rebuild')")
        con.commit()
    tempo_s = round(time.perf_counter() - inicio, 2)
    return True, f"Indice FTS5 reconstruido em {tempo_s}s."


def indice_fts_base_pesquisa_existe(caminho_sqlite):
    return objeto_sqlite_existe(caminho_sqlite, FTS_BASE_PESQUISA, tipo="table")


def carregar_candidatos_fts_base_pesquisa(
    caminho_sqlite,
    descricao_busca,
    criterios,
    limite=15000,
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
):
    inicio = time.perf_counter()
    if not indice_fts_base_pesquisa_existe(caminho_sqlite):
        return None

    matches = montar_matches_fts(descricao_busca, criterios)
    if not matches:
        return None

    filtro_municipio, parametros_excluir = _filtro_exclusao_municipio(
        "base_pesquisa",
        excluir_municipio,
    )
    pre_limite = max(limite, min(limite * 2, 1200))

    sql = f"""
        WITH fts_hits AS (
            SELECT
                rowid AS fts_rowid,
                bm25({FTS_BASE_PESQUISA}) AS fts_rank
            FROM {FTS_BASE_PESQUISA}
            WHERE {FTS_BASE_PESQUISA} MATCH ?
            ORDER BY fts_rank
            LIMIT ?
        )
        SELECT
            b.linha_csv AS "Linha CSV",
            b.item AS "Item",
            b.qtd AS "Qtd.",
            b.unidade AS "Un.",
            b.valor_unitario AS "Vl. Un. Homolog.",
            b.valor_total AS "Vl. Total Homolog.",
            b.orgao AS "Orgao",
            b.modalidade AS "Modalidade",
            b.nr AS "Nr.",
            b.ano AS "Ano",
            b.objeto AS "Objeto",
            b.abertura AS "Abertura",
            b.data_homologacao AS "Data Homologacao",
            b.vencedor AS "Vencedor",
            b.cpf_cnpj AS "CPF/CNPJ",
            b.link_licitacon AS "Link LicitaCon",
            '' AS "Municipio Fonte",
            '' AS "Grupo Regional",
            'LicitaCon geral' AS "Fonte Base",
            h.fts_rank AS "_fts_rank"
        FROM fts_hits h
        JOIN base_pesquisa b ON b.rowid = h.fts_rowid
        WHERE b.item IS NOT NULL
          AND TRIM(b.item) <> ''
          AND b.valor_unitario IS NOT NULL
          AND TRIM(b.valor_unitario) NOT IN ('', '0', '0.00')
          AND CAST(REPLACE(b.valor_unitario, ',', '.') AS REAL) > 0
          AND b.vencedor IS NOT NULL
          AND TRIM(b.vencedor) NOT IN ('', '-', '--', 'nan', 'None', 'NULL')
          {filtro_municipio}
        ORDER BY h.fts_rank
        LIMIT ?
    """

    frames = []
    matches_executados = []
    with conectar_licitacon(caminho_sqlite) as con:
        for nome_estrategia, match in matches:
            matches_executados.append((nome_estrategia, match))
            parametros = [match, pre_limite] + parametros_excluir + [limite]
            inicio_tentativa = time.perf_counter()
            df_tentativa = pd.read_sql_query(sql, con, params=parametros, dtype=str)
            df_tentativa["_fts_strategy"] = nome_estrategia
            frames.append(df_tentativa)
            logger.info(
                "FTS5 tentativa=%s match=%s candidatos=%s tempo_ms=%s",
                nome_estrategia,
                match,
                len(df_tentativa),
                round((time.perf_counter() - inicio_tentativa) * 1000, 2),
            )
            if _strict_zero_deve_abortar(nome_estrategia, len(df_tentativa), descricao_busca):
                logger.info(
                    "[expansao_hard_abort] origem=fts5 tentativa=%s motivo_aborto=baixa_aderencia match=%s",
                    nome_estrategia,
                    match,
                )
                continue
            if nome_estrategia.startswith("and_") and len(df_tentativa) == 0:
                logger.info(
                    "[semantic_fallback] tentativa=%s candidatos=0 acao=continuar_sem_atributos_fracos match=%s",
                    nome_estrategia,
                    match,
                )
            if _strict_first_deve_parar(nome_estrategia, len(df_tentativa), limite, descricao_busca):
                logger.info(
                    "FTS5 strict_first_stop tentativa=%s candidatos=%s limite=%s",
                    nome_estrategia,
                    len(df_tentativa),
                    limite,
                )
                break
            if len(pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Linha CSV", "Item", "Orgao"])) >= limite:
                break

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(subset=["Linha CSV", "Item", "Orgao"]).head(limite)

    return _registrar_resultado_busca(
        df,
        "fts5_multi",
        inicio,
        len(df),
        detalhe="; ".join(f"{nome}={match}" for nome, match in matches_executados),
        banco="raw",
        caminho=caminho_sqlite,
    )


def carregar_candidatos_like_sqlite(
    caminho_sqlite,
    descricao_busca,
    criterios,
    limite=15000,
    tabela="base_pesquisa",
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
    ordenar_por_relevancia=True,
):
    inicio = time.perf_counter()
    tabela = validar_tabela(tabela)

    if not tabela_sqlite_existe(caminho_sqlite, tabela):
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
    campos_extras = TABELAS_SQLITE_BUSCA[tabela].campos_extras
    filtro_municipio, parametros_excluir = _filtro_exclusao_municipio(
        tabela,
        excluir_municipio,
    )

    ordenacao = """
        ORDER BY
            _relevancia DESC,
            CASE
                WHEN valor_unitario IS NOT NULL
                 AND TRIM(valor_unitario) NOT IN ('', '0', '0.00') THEN 0
                ELSE 1
            END,
            ano DESC
    """ if ordenar_por_relevancia else ""

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
          {filtro_municipio}
        {ordenacao}
        LIMIT ?
    """

    parametros = parametros_filtro + parametros_relevancia + parametros_excluir + [limite]

    with conectar_licitacon(caminho_sqlite) as con:
        df = pd.read_sql_query(sql, con, params=parametros, dtype=str)

    return _registrar_resultado_busca(
        df,
        "like",
        inicio,
        len(df),
        detalhe=f"termos={','.join(termos)}",
        banco="raw",
        caminho=caminho_sqlite,
    )


def indice_fts_operacional_existe(caminho_sqlite):
    return (
        objeto_sqlite_existe(caminho_sqlite, TABELA_OPERACIONAL, tipo="table")
        and objeto_sqlite_existe(caminho_sqlite, FTS_OPERACIONAL, tipo="table")
    )


def carregar_candidatos_operacional(
    caminho_sqlite,
    descricao_busca,
    criterios,
    limite=15000,
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
):
    inicio = time.perf_counter()
    if not indice_fts_operacional_existe(caminho_sqlite):
        return None

    matches = montar_matches_fts(descricao_busca, criterios)
    if not matches:
        return None

    filtro_municipio, parametros_excluir = _filtro_exclusao_operacional(
        excluir_municipio,
    )
    pre_limite = max(limite, min(limite * 2, 1200))

    sql = f"""
        WITH fts_hits AS (
            SELECT
                rowid AS fts_rowid,
                bm25({FTS_OPERACIONAL}) AS fts_rank
            FROM {FTS_OPERACIONAL}
            WHERE {FTS_OPERACIONAL} MATCH ?
            ORDER BY fts_rank
            LIMIT ?
        )
        SELECT
            o.linha_csv AS "Linha CSV",
            o.item AS "Item",
            o.quantidade AS "Qtd.",
            o.unidade AS "Un.",
            o.valor_unitario AS "Vl. Un. Homolog.",
            o.valor_total AS "Vl. Total Homolog.",
            o.orgao AS "Orgao",
            o.modalidade AS "Modalidade",
            o.processo AS "Nr.",
            o.ano AS "Ano",
            o.objeto AS "Objeto",
            '' AS "Abertura",
            o.data_homologacao AS "Data Homologacao",
            o.fornecedor AS "Vencedor",
            o.cpf_cnpj AS "CPF/CNPJ",
            o.link_licitacon AS "Link LicitaCon",
            o.municipio AS "Municipio Fonte",
            o.grupo_regional AS "Grupo Regional",
            o.fonte AS "Fonte Base",
            h.fts_rank AS "_fts_rank",
            o.id AS "_operacional_id",
            o.source_table AS "_source_table",
            o.source_rowid AS "_source_rowid"
        FROM fts_hits h
        JOIN {TABELA_OPERACIONAL} o ON o.id = h.fts_rowid
        WHERE o.item IS NOT NULL
          AND TRIM(o.item) <> ''
          AND o.valor_unitario IS NOT NULL
          AND o.valor_unitario > 0
          AND o.fornecedor IS NOT NULL
          AND TRIM(o.fornecedor) NOT IN ('', '-', '--', 'nan', 'None', 'NULL')
          {filtro_municipio}
        ORDER BY h.fts_rank
        LIMIT ?
    """

    frames = []
    matches_executados = []
    with conectar_licitacon(caminho_sqlite) as con:
        for nome_estrategia, match in matches:
            matches_executados.append((nome_estrategia, match))
            parametros = [match, pre_limite] + parametros_excluir + [limite]
            inicio_tentativa = time.perf_counter()
            df_tentativa = pd.read_sql_query(sql, con, params=parametros, dtype=str)
            df_tentativa["_fts_strategy"] = nome_estrategia
            frames.append(df_tentativa)
            logger.info(
                "FTS5 operacional tentativa=%s match=%s candidatos=%s tempo_ms=%s",
                nome_estrategia,
                match,
                len(df_tentativa),
                round((time.perf_counter() - inicio_tentativa) * 1000, 2),
            )
            if _strict_zero_deve_abortar(nome_estrategia, len(df_tentativa), descricao_busca):
                logger.info(
                    "[expansao_hard_abort] origem=fts5_operacional tentativa=%s motivo_aborto=baixa_aderencia match=%s",
                    nome_estrategia,
                    match,
                )
                continue
            if nome_estrategia.startswith("and_") and len(df_tentativa) == 0:
                logger.info(
                    "[semantic_fallback] tentativa=%s candidatos=0 acao=continuar_sem_atributos_fracos match=%s",
                    nome_estrategia,
                    match,
                )
            if _strict_first_deve_parar(nome_estrategia, len(df_tentativa), limite, descricao_busca):
                logger.info(
                    "FTS5 operacional strict_first_stop tentativa=%s candidatos=%s limite=%s",
                    nome_estrategia,
                    len(df_tentativa),
                    limite,
                )
                break
            if len(pd.concat(frames, ignore_index=True).drop_duplicates(subset=["_operacional_id"])) >= limite:
                break

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(subset=["_operacional_id"]).head(limite)

    return _registrar_resultado_busca(
        df,
        "fts5_operational_multi",
        inicio,
        len(df),
        detalhe="; ".join(f"{nome}={match}" for nome, match in matches_executados),
        banco="operational",
        caminho=caminho_sqlite,
    )


def carregar_candidatos_runtime(
    descricao_busca,
    criterios,
    limite=15000,
    mode="auto",
    raw_path=path_str(DEFAULT_RAW_DB_PATH),
    operational_path=path_str(DEFAULT_OPERATIONAL_DB_PATH),
    tabela="base_pesquisa",
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
    ordenar_por_relevancia=False,
):
    mode = (mode or "auto").strip().lower()
    if mode not in {"auto", "raw", "operational"}:
        mode = "auto"

    tentativas = []
    if mode == "operational":
        tentativas = ["operational"]
    elif mode == "raw":
        tentativas = ["raw"]
    else:
        tentativas = ["operational", "raw"]

    erros = []
    for tentativa in tentativas:
        try:
            if tentativa == "operational":
                chave_cache, nucleo = _cache_key_candidatos(
                    "operational",
                    operational_path,
                    descricao_busca,
                    limite,
                    excluir_municipio,
                )
                cached = _obter_cache_candidatos(chave_cache, nucleo.get("semantic_core", ""))
                if cached is not None:
                    cached.attrs["sqlite_search"]["mode"] = mode
                    cached.attrs["sqlite_search"]["fallback"] = mode == "auto" and tentativa != tentativas[0]
                    return cached
                descricao_sqlite = nucleo.get("search_core") or descricao_busca
                df = carregar_candidatos_operacional(
                    caminho_sqlite=operational_path,
                    descricao_busca=descricao_sqlite,
                    criterios=criterios,
                    limite=limite,
                    excluir_municipio=excluir_municipio,
                )
                if df is not None and (not df.empty or df.attrs.get("sqlite_search")):
                    df = _salvar_cache_candidatos(chave_cache, df, nucleo.get("semantic_core", ""))
                    df.attrs["sqlite_search"]["mode"] = mode
                    df.attrs["sqlite_search"]["fallback"] = mode == "auto" and tentativa != tentativas[0]
                    df.attrs["sqlite_search"]["descricao_original"] = descricao_busca
                    df.attrs["sqlite_search"]["descricao_sqlite"] = descricao_sqlite
                    return df
                erros.append("operational indisponivel ou sem candidatos")
            else:
                chave_cache, nucleo = _cache_key_candidatos(
                    "raw",
                    raw_path,
                    descricao_busca,
                    limite,
                    excluir_municipio,
                )
                cached = _obter_cache_candidatos(chave_cache, nucleo.get("semantic_core", ""))
                if cached is not None:
                    cached.attrs["sqlite_search"]["mode"] = mode
                    cached.attrs["sqlite_search"]["fallback"] = mode == "auto" and tentativa != tentativas[0]
                    return cached
                descricao_sqlite = nucleo.get("search_core") or descricao_busca
                df = carregar_candidatos_sqlite(
                    caminho_sqlite=raw_path,
                    descricao_busca=descricao_sqlite,
                    criterios=criterios,
                    limite=limite,
                    tabela=tabela,
                    excluir_municipio=excluir_municipio,
                    ordenar_por_relevancia=ordenar_por_relevancia,
                    usar_fts=True,
                )
                if df is not None and (not df.empty or df.attrs.get("sqlite_search")):
                    df = _salvar_cache_candidatos(chave_cache, df, nucleo.get("semantic_core", ""))
                    df.attrs["sqlite_search"]["mode"] = mode
                    df.attrs["sqlite_search"]["fallback"] = mode == "auto" and tentativa != tentativas[0]
                    df.attrs["sqlite_search"]["descricao_original"] = descricao_busca
                    df.attrs["sqlite_search"]["descricao_sqlite"] = descricao_sqlite
                    return df
                erros.append("raw sem candidatos")
        except Exception as erro:
            erros.append(f"{tentativa}: {erro}")
            logger.warning("Falha no banco %s em modo %s: %s", tentativa, mode, erro)

    raise RuntimeError("Nenhum banco de busca retornou candidatos. " + " | ".join(erros))


def carregar_candidatos_sqlite(
    caminho_sqlite,
    descricao_busca,
    criterios,
    limite=15000,
    tabela="base_pesquisa",
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
    ordenar_por_relevancia=True,
    usar_fts=True,
):
    tabela = validar_tabela(tabela)

    if usar_fts and tabela == "base_pesquisa":
        try:
            candidatos_fts = carregar_candidatos_fts_base_pesquisa(
                caminho_sqlite=caminho_sqlite,
                descricao_busca=descricao_busca,
                criterios=criterios,
                limite=limite,
                excluir_municipio=excluir_municipio,
            )
            if candidatos_fts is not None and not candidatos_fts.empty:
                return candidatos_fts
            if candidatos_fts is not None:
                logger.info("FTS5 sem candidatos; usando fallback LIKE.")
        except Exception as erro:
            logger.warning("Falha na busca FTS5; usando fallback LIKE: %s", erro)

    return carregar_candidatos_like_sqlite(
        caminho_sqlite=caminho_sqlite,
        descricao_busca=descricao_busca,
        criterios=criterios,
        limite=limite,
        tabela=tabela,
        excluir_municipio=excluir_municipio,
        ordenar_por_relevancia=ordenar_por_relevancia,
    )
