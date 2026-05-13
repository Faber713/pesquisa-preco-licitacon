import argparse
import csv
import re
import sqlite3
import time
from pathlib import Path

from database.raw.importar_licitacon import (
    ARQUIVOS_OBRIGATORIOS,
    colunas_unicas,
    configurar_conexao,
    quote_ident,
    tabela_existe,
    validar_arquivos,
)


GRUPOS_REGIONAIS = {
    "joia": "local",
    "augusto-pestana": "entorno",
    "boa-vista-do-cadeado": "entorno",
    "catuipe": "entorno",
    "coronel-barros": "entorno",
    "entre-ijuis": "entorno",
    "eugenio-de-castro": "entorno",
    "pejucara": "entorno",
    "cruz-alta": "polo_regional",
    "ijui": "polo_regional",
    "panambi": "polo_regional",
    "santo-angelo": "polo_regional",
    "tupancireta": "polo_regional",
}


def slug_da_pasta(pasta):
    nome = pasta.name.lower()
    nome = re.sub(r"\.csv$", "", nome)
    nome = re.sub(r"^licitacoes-pm-de-", "", nome)
    nome = re.sub(r"[^a-z0-9-]+", "-", nome)
    return nome.strip("-")


def nome_municipio(slug):
    especiais = {
        "ijui": "Ijui",
        "joia": "Joia",
        "catuipe": "Catuipe",
        "entre-ijuis": "Entre-Ijuis",
        "eugenio-de-castro": "Eugenio de Castro",
        "pejucara": "Pejucara",
        "santo-angelo": "Santo Angelo",
        "tupancireta": "Tupancireta",
    }

    if slug in especiais:
        return especiais[slug]

    return " ".join(parte.capitalize() for parte in slug.split("-"))


def preparar_tabela_fontes(con):
    con.execute("DROP TABLE IF EXISTS fontes_municipais")
    con.execute(
        """
        CREATE TABLE fontes_municipais (
            fonte_id TEXT PRIMARY KEY,
            municipio TEXT NOT NULL,
            pasta TEXT NOT NULL,
            grupo_regional TEXT NOT NULL,
            data_importacao TEXT NOT NULL,
            status TEXT NOT NULL,
            total_itens INTEGER DEFAULT 0
        )
        """
    )


def importar_csv_municipal(con, caminho_csv, tabela, fonte_id, municipio, grupo, lote=20000):
    inicio = time.time()
    print(f"Importando {municipio}/{caminho_csv.name} -> {tabela}...")

    with caminho_csv.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        colunas = colunas_unicas(cabecalho)

        if not tabela_existe(con, tabela):
            definicao_colunas = ", ".join(
                f"{quote_ident(coluna)} TEXT"
                for coluna in colunas
            )
            con.execute(
                f"CREATE TABLE {quote_ident(tabela)} "
                f"(FONTE_ID TEXT, MUNICIPIO TEXT, GRUPO_REGIONAL TEXT, "
                f"_linha_arquivo INTEGER, {definicao_colunas})"
            )

        placeholders = ", ".join(["?"] * (len(colunas) + 4))
        nomes_colunas = ", ".join(
            [
                quote_ident("FONTE_ID"),
                quote_ident("MUNICIPIO"),
                quote_ident("GRUPO_REGIONAL"),
                quote_ident("_linha_arquivo"),
            ]
            + [quote_ident(c) for c in colunas]
        )
        sql = (
            f"INSERT INTO {quote_ident(tabela)} ({nomes_colunas}) "
            f"VALUES ({placeholders})"
        )

        buffer = []
        total = 0

        for numero_linha, linha in enumerate(leitor, start=2):
            if len(linha) < len(colunas):
                linha += [""] * (len(colunas) - len(linha))
            elif len(linha) > len(colunas):
                linha = linha[:len(colunas)]

            buffer.append([fonte_id, municipio, grupo, numero_linha] + linha)

            if len(buffer) >= lote:
                con.executemany(sql, buffer)
                total += len(buffer)
                buffer.clear()

                if total % (lote * 10) == 0:
                    print(f"  {tabela}: {total:,} linhas".replace(",", "."))

        if buffer:
            con.executemany(sql, buffer)
            total += len(buffer)

    con.commit()

    duracao = time.time() - inicio
    print(f"Concluido {municipio}/{tabela}: {total:,} linhas em {duracao:.1f}s".replace(",", "."))
    return total


def criar_indices_municipais(con):
    print("Criando indices das bases municipais...")

    indices = [
        """
        CREATE INDEX IF NOT EXISTS idx_municipio_licitacao_chave
        ON municipio_licitacao (FONTE_ID, CD_ORGAO, NR_LICITACAO, ANO_LICITACAO, CD_TIPO_MODALIDADE)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_municipio_item_chave
        ON municipio_item (FONTE_ID, CD_ORGAO, NR_LICITACAO, ANO_LICITACAO, CD_TIPO_MODALIDADE)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_municipio_item_descricao
        ON municipio_item (DS_ITEM)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_municipio_pessoas_documento
        ON municipio_pessoas (FONTE_ID, CD_ORGAO, TP_DOCUMENTO, NR_DOCUMENTO)
        """,
    ]

    for sql in indices:
        con.execute(sql)

    con.commit()


def criar_base_historica_municipios(con):
    print("Criando tabela consolidada base_historica_municipios...")

    con.execute("DROP TABLE IF EXISTS base_historica_municipios")

    con.execute(
        """
        CREATE TABLE base_historica_municipios AS
        SELECT
            i.FONTE_ID AS fonte_id,
            i.MUNICIPIO AS municipio,
            i.GRUPO_REGIONAL AS grupo_regional,
            i._linha_arquivo AS linha_csv,
            i.CD_ORGAO AS cd_orgao,
            l.NM_ORGAO AS orgao,
            i.NR_LICITACAO AS nr,
            i.ANO_LICITACAO AS ano,
            i.CD_TIPO_MODALIDADE AS modalidade,
            i.NR_LOTE AS lote,
            i.NR_ITEM AS nr_item,
            i.DS_ITEM AS item,
            i.QT_ITENS AS qtd,
            i.SG_UNIDADE_MEDIDA AS unidade,
            i.VL_UNITARIO_ESTIMADO AS valor_unitario_estimado,
            i.VL_TOTAL_ESTIMADO AS valor_total_estimado,
            i.VL_UNITARIO_HOMOLOGADO AS valor_unitario,
            i.VL_TOTAL_HOMOLOGADO AS valor_total,
            i.TP_RESULTADO_ITEM AS resultado_item,
            l.DS_OBJETO AS objeto,
            l.DT_ABERTURA AS abertura,
            l.DT_HOMOLOGACAO AS data_homologacao,
            l.LINK_LICITACON_CIDADAO AS link_licitacon,
            COALESCE(i.TP_DOCUMENTO, i.TP_DOCUMENTO_2, l.TP_DOCUMENTO_VENCEDOR) AS tp_documento_vencedor,
            COALESCE(i.NR_DOCUMENTO, i.NR_DOCUMENTO_2, l.NR_DOCUMENTO_VENCEDOR) AS cpf_cnpj,
            COALESCE(p1.NM_PESSOA, p2.NM_PESSOA, p3.NM_PESSOA) AS vencedor
        FROM municipio_item i
        LEFT JOIN municipio_licitacao l
            ON l.FONTE_ID = i.FONTE_ID
           AND l.CD_ORGAO = i.CD_ORGAO
           AND l.NR_LICITACAO = i.NR_LICITACAO
           AND l.ANO_LICITACAO = i.ANO_LICITACAO
           AND l.CD_TIPO_MODALIDADE = i.CD_TIPO_MODALIDADE
        LEFT JOIN municipio_pessoas p1
            ON p1.FONTE_ID = i.FONTE_ID
           AND p1.CD_ORGAO = i.CD_ORGAO
           AND p1.TP_DOCUMENTO = i.TP_DOCUMENTO
           AND p1.NR_DOCUMENTO = i.NR_DOCUMENTO
        LEFT JOIN municipio_pessoas p2
            ON p2.FONTE_ID = i.FONTE_ID
           AND p2.CD_ORGAO = i.CD_ORGAO
           AND p2.TP_DOCUMENTO = i.TP_DOCUMENTO_2
           AND p2.NR_DOCUMENTO = i.NR_DOCUMENTO_2
        LEFT JOIN municipio_pessoas p3
            ON p3.FONTE_ID = i.FONTE_ID
           AND p3.CD_ORGAO = i.CD_ORGAO
           AND p3.TP_DOCUMENTO = l.TP_DOCUMENTO_VENCEDOR
           AND p3.NR_DOCUMENTO = l.NR_DOCUMENTO_VENCEDOR
        WHERE i.DS_ITEM IS NOT NULL
          AND TRIM(i.DS_ITEM) <> ''
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_historica_item
        ON base_historica_municipios (item)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_historica_homologado
        ON base_historica_municipios (valor_unitario, vencedor)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_historica_municipio
        ON base_historica_municipios (municipio, grupo_regional, ano)
        """
    )
    con.commit()

    total = con.execute("SELECT COUNT(*) FROM base_historica_municipios").fetchone()[0]
    print(f"base_historica_municipios criada com {total:,} linhas".replace(",", "."))


def importar_pastas(args):
    raiz = Path(args.pasta)
    pastas = sorted(p for p in raiz.iterdir() if p.is_dir())

    if not pastas:
        raise FileNotFoundError(f"Nenhuma pasta municipal encontrada em: {raiz}")

    for pasta in pastas:
        validar_arquivos(pasta)

    con = sqlite3.connect(args.saida)
    inicio = time.time()

    try:
        configurar_conexao(con)

        for tabela in ARQUIVOS_OBRIGATORIOS:
            con.execute(f"DROP TABLE IF EXISTS {quote_ident('municipio_' + tabela)}")
        con.execute("DROP TABLE IF EXISTS base_historica_municipios")
        preparar_tabela_fontes(con)
        con.commit()

        for pasta in pastas:
            fonte_id = slug_da_pasta(pasta)
            municipio = nome_municipio(fonte_id)
            grupo = GRUPOS_REGIONAIS.get(fonte_id, "regional_ampliado")
            total_itens = 0

            for tabela, nome_arquivo in ARQUIVOS_OBRIGATORIOS.items():
                total = importar_csv_municipal(
                    con=con,
                    caminho_csv=pasta / nome_arquivo,
                    tabela="municipio_" + tabela,
                    fonte_id=fonte_id,
                    municipio=municipio,
                    grupo=grupo,
                    lote=args.lote,
                )
                if tabela == "item":
                    total_itens = total

            con.execute(
                """
                INSERT INTO fontes_municipais
                (fonte_id, municipio, pasta, grupo_regional, data_importacao, status, total_itens)
                VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                (fonte_id, municipio, str(pasta), grupo, "importado", total_itens),
            )
            con.commit()

        criar_indices_municipais(con)
        criar_base_historica_municipios(con)

    finally:
        con.close()

    duracao = time.time() - inicio
    print(f"Importacao municipal finalizada em {duracao:.1f}s")
    print(f"Base atualizada em: {Path(args.saida).resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Importa bases historicas municipais para tabela separada no SQLite."
    )
    parser.add_argument(
        "--pasta",
        default="bases_dados/municipios_regionais",
        help="Pasta que contem subpastas municipais com licitacao.csv, item.csv e pessoas.csv.",
    )
    parser.add_argument(
        "--saida",
        default="licitacon.sqlite",
        help="Arquivo SQLite que sera atualizado.",
    )
    parser.add_argument(
        "--lote",
        type=int,
        default=20000,
        help="Quantidade de linhas por lote de insercao.",
    )

    importar_pastas(parser.parse_args())


if __name__ == "__main__":
    main()
