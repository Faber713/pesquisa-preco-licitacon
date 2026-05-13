import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from util import normalizar, palavras_fortes


MUNICIPIO_PROPRIO_PADRAO = "Joia"


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


def base_sqlite_disponivel(caminho_sqlite, tabela="base_pesquisa"):
    caminho = Path(caminho_sqlite)
    if not caminho.exists():
        return False, f"Arquivo da base LicitaCon nao encontrado: {caminho}"

    try:
        with conectar_licitacon(caminho) as con:
            con.execute(f"SELECT 1 FROM {validar_tabela(tabela)} LIMIT 1").fetchone()
        return True, ""
    except Exception as erro:
        return False, f"Nao foi possivel abrir a base SQLite: {erro}"


def validar_tabela(tabela):
    if tabela not in TABELAS_SQLITE_BUSCA:
        raise ValueError(f"Tabela de busca nao permitida: {tabela}")
    return tabela


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


def carregar_candidatos_sqlite(
    caminho_sqlite,
    descricao_busca,
    criterios,
    limite=15000,
    tabela="base_pesquisa",
    excluir_municipio=MUNICIPIO_PROPRIO_PADRAO,
):
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
        ORDER BY
            _relevancia DESC,
            CASE
                WHEN valor_unitario IS NOT NULL
                 AND TRIM(valor_unitario) NOT IN ('', '0', '0.00') THEN 0
                ELSE 1
            END,
            ano DESC
        LIMIT ?
    """

    parametros = parametros_filtro + parametros_relevancia + parametros_excluir + [limite]

    with conectar_licitacon(caminho_sqlite) as con:
        return pd.read_sql_query(sql, con, params=parametros, dtype=str)


def sql_criar_fts_base_pesquisa():
    return """
    CREATE VIRTUAL TABLE IF NOT EXISTS base_pesquisa_fts
    USING fts5(
        item,
        objeto,
        orgao,
        vencedor,
        content='base_pesquisa',
        content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 2'
    );
    """

