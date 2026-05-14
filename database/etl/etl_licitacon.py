import argparse
import os
import sqlite3
import time
from pathlib import Path

from database.paths import DEFAULT_OPERATIONAL_DB_PATH, DEFAULT_RAW_DB_PATH, path_str
from utils.util import normalizar


TABELA_OPERACIONAL = "base_pesquisa_operacional"
TABELA_FTS = "base_pesquisa_operacional_fts"


def configurar_conexao(con):
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -200000")
    con.create_function("NORMALIZAR_TEXTO", 1, lambda valor: normalizar(valor or ""))


def tabela_existe(con, nome_tabela):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (nome_tabela,),
    ).fetchone() is not None


def tabela_origem_existe(con, nome_tabela):
    return con.execute(
        "SELECT 1 FROM src.sqlite_master WHERE type = 'table' AND name = ?",
        (nome_tabela,),
    ).fetchone() is not None


def sqlite_suporta_fts5(con):
    try:
        con.execute("CREATE VIRTUAL TABLE temp.teste_fts USING fts5(texto)")
        return True
    except sqlite3.Error:
        return False


def criar_schema(con):
    con.executescript(
        f"""
        DROP TABLE IF EXISTS {TABELA_FTS};
        DROP TABLE IF EXISTS {TABELA_OPERACIONAL};

        CREATE TABLE {TABELA_OPERACIONAL} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origem TEXT NOT NULL,
            fonte TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_rowid INTEGER,
            linha_csv INTEGER,
            item TEXT NOT NULL,
            item_normalizado TEXT NOT NULL,
            orgao TEXT,
            municipio TEXT,
            modalidade TEXT,
            ano INTEGER,
            fornecedor TEXT,
            cpf_cnpj TEXT,
            valor_unitario REAL NOT NULL,
            valor_total REAL,
            quantidade REAL,
            unidade TEXT,
            objeto TEXT,
            data_homologacao TEXT,
            processo TEXT,
            lote TEXT,
            nr_item TEXT,
            link_licitacon TEXT,
            grupo_regional TEXT
        );
        """
    )


def _insert_sql(tabela_origem, regional=False):
    municipio = "municipio" if regional else "''"
    grupo = "grupo_regional" if regional else "''"
    fonte = "'Historico regional'" if regional else "'LicitaCon geral'"
    origem = "'regional'" if regional else "'geral'"

    return f"""
        INSERT INTO {TABELA_OPERACIONAL} (
            origem, fonte, source_table, source_rowid, linha_csv,
            item, item_normalizado, orgao, municipio, modalidade, ano,
            fornecedor, cpf_cnpj, valor_unitario, valor_total, quantidade, unidade,
            objeto, data_homologacao, processo, lote, nr_item, link_licitacon,
            grupo_regional
        )
        SELECT
            {origem} AS origem,
            {fonte} AS fonte,
            '{tabela_origem}' AS source_table,
            rowid AS source_rowid,
            CAST(linha_csv AS INTEGER) AS linha_csv,
            item,
            NORMALIZAR_TEXTO(item) AS item_normalizado,
            orgao,
            {municipio} AS municipio,
            modalidade,
            CAST(NULLIF(ano, '') AS INTEGER) AS ano,
            vencedor AS fornecedor,
            cpf_cnpj,
            CAST(REPLACE(valor_unitario, ',', '.') AS REAL) AS valor_unitario,
            CAST(REPLACE(valor_total, ',', '.') AS REAL) AS valor_total,
            CAST(REPLACE(qtd, ',', '.') AS REAL) AS quantidade,
            unidade,
            objeto,
            data_homologacao,
            (COALESCE(nr, '') || '/' || COALESCE(ano, '')) AS processo,
            lote,
            nr_item,
            link_licitacon,
            {grupo} AS grupo_regional
        FROM src.{tabela_origem}
        WHERE item IS NOT NULL
          AND TRIM(item) <> ''
          AND valor_unitario IS NOT NULL
          AND TRIM(valor_unitario) NOT IN ('', '0', '0.00')
          AND CAST(REPLACE(valor_unitario, ',', '.') AS REAL) > 0
          AND vencedor IS NOT NULL
          AND TRIM(vencedor) NOT IN ('', '-', '--', 'nan', 'None', 'NULL')
    """


def carregar_operacional(con, incluir_regional=True):
    total_inserido = 0

    if tabela_origem_existe(con, "base_pesquisa"):
        antes = con.total_changes
        con.execute(_insert_sql("base_pesquisa", regional=False))
        total_inserido += con.total_changes - antes

    if incluir_regional and tabela_origem_existe(con, "base_historica_municipios"):
        antes = con.total_changes
        con.execute(_insert_sql("base_historica_municipios", regional=True))
        total_inserido += con.total_changes - antes

    con.commit()
    return total_inserido


def criar_indices(con):
    con.executescript(
        f"""
        CREATE INDEX IF NOT EXISTS idx_operacional_item_norm
        ON {TABELA_OPERACIONAL}(item_normalizado);

        CREATE INDEX IF NOT EXISTS idx_operacional_ano
        ON {TABELA_OPERACIONAL}(ano);

        CREATE INDEX IF NOT EXISTS idx_operacional_modalidade
        ON {TABELA_OPERACIONAL}(modalidade);

        CREATE INDEX IF NOT EXISTS idx_operacional_valor
        ON {TABELA_OPERACIONAL}(valor_unitario);

        CREATE INDEX IF NOT EXISTS idx_operacional_fonte
        ON {TABELA_OPERACIONAL}(fonte, municipio, grupo_regional);

        CREATE INDEX IF NOT EXISTS idx_operacional_fornecedor
        ON {TABELA_OPERACIONAL}(fornecedor);
        """
    )
    con.commit()


def criar_fts(con):
    if not sqlite_suporta_fts5(con):
        raise RuntimeError("SQLite local nao suporta FTS5.")

    con.executescript(
        f"""
        CREATE VIRTUAL TABLE {TABELA_FTS}
        USING fts5(
            item,
            item_normalizado,
            objeto,
            orgao,
            modalidade,
            fornecedor,
            content='{TABELA_OPERACIONAL}',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );

        INSERT INTO {TABELA_FTS}({TABELA_FTS}) VALUES ('rebuild');
        """
    )
    con.commit()


def estatisticas(con, caminho_origem, caminho_saida, duracao_s):
    total = con.execute(f"SELECT COUNT(*) FROM {TABELA_OPERACIONAL}").fetchone()[0]
    fts_total = con.execute(f"SELECT COUNT(*) FROM {TABELA_FTS}").fetchone()[0]
    return {
        "origem": str(Path(caminho_origem).resolve()),
        "saida": str(Path(caminho_saida).resolve()),
        "tamanho_origem_bytes": os.path.getsize(caminho_origem),
        "tamanho_saida_bytes": os.path.getsize(caminho_saida),
        "registros_operacionais": total,
        "registros_fts": fts_total,
        "duracao_s": round(duracao_s, 2),
    }


def criar_base_operacional(origem, saida, incluir_regional=True):
    origem = Path(origem)
    saida = Path(saida)

    if not origem.exists():
        raise FileNotFoundError(f"Base origem nao encontrada: {origem}")

    saida.parent.mkdir(parents=True, exist_ok=True)
    if saida.exists():
        saida.unlink()

    inicio = time.perf_counter()
    con = sqlite3.connect(saida)
    try:
        configurar_conexao(con)
        con.execute("ATTACH DATABASE ? AS src", (str(origem),))
        criar_schema(con)
        total = carregar_operacional(con, incluir_regional=incluir_regional)
        if total == 0:
            raise RuntimeError("Nenhum registro operacional foi gerado.")
        criar_indices(con)
        criar_fts(con)
        con.execute("DETACH DATABASE src")
        con.commit()
        return estatisticas(con, origem, saida, time.perf_counter() - inicio)
    finally:
        con.close()


def benchmark_busca(saida, termo='"rele"* OR "falta"* OR "fase"* OR "380v"*', limite=1200):
    inicio = time.perf_counter()
    con = sqlite3.connect(saida)
    try:
        rows = con.execute(
            f"""
            SELECT o.id, o.item, o.orgao, o.valor_unitario
            FROM {TABELA_FTS} f
            JOIN {TABELA_OPERACIONAL} o ON o.id = f.rowid
            WHERE {TABELA_FTS} MATCH ?
            ORDER BY bm25({TABELA_FTS})
            LIMIT ?
            """,
            (termo, limite),
        ).fetchall()
        return {
            "termo": termo,
            "limite": limite,
            "resultados": len(rows),
            "tempo_ms": round((time.perf_counter() - inicio) * 1000, 2),
        }
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(
        description="Cria banco operacional enxuto para busca inteligente LicitaCon."
    )
    parser.add_argument("--origem", default=path_str(DEFAULT_RAW_DB_PATH))
    parser.add_argument("--saida", default=path_str(DEFAULT_OPERATIONAL_DB_PATH))
    parser.add_argument("--sem-regional", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()

    stats = criar_base_operacional(
        origem=args.origem,
        saida=args.saida,
        incluir_regional=not args.sem_regional,
    )
    print("ETL operacional concluido:")
    for chave, valor in stats.items():
        print(f"- {chave}: {valor}")

    if args.benchmark:
        print("Benchmark FTS5:")
        for chave, valor in benchmark_busca(args.saida).items():
            print(f"- {chave}: {valor}")


if __name__ == "__main__":
    main()
