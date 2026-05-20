import argparse
import csv
import re
import sqlite3
import time
from pathlib import Path

from database.paths import DEFAULT_RAW_DB_PATH, garantir_diretorios_database, path_str

ANO_MINIMO_PADRAO = 2024

ARQUIVOS_BASE_PESQUISA = {
    "licitacao": "licitacao.csv",
    "item": "item.csv",
    "pessoas": "pessoas.csv",
}

ARQUIVOS_PRIORITARIOS = {
    **ARQUIVOS_BASE_PESQUISA,
    "item_prop": "item_prop.csv",
    "proposta": "proposta.csv",
    "licitante": "licitante.csv",
}

ARQUIVOS_DISPONIVEIS = {
    **ARQUIVOS_PRIORITARIOS,
    "comissao": "comissao.csv",
    "documento_lic": "documento_lic.csv",
    "dotacao_lic": "dotacao_lic.csv",
    "evento_lic": "evento_lic.csv",
    "lote": "lote.csv",
    "lote_prop": "lote_prop.csv",
    "membrocons": "membrocons.csv",
    "memcomissao": "memcomissao.csv",
}

# Mantido para compatibilidade com importadores municipais existentes.
ARQUIVOS_OBRIGATORIOS = ARQUIVOS_BASE_PESQUISA


def quote_ident(nome):
    return '"' + str(nome).replace('"', '""') + '"'


def normalizar_nome_coluna(nome):
    nome = str(nome).strip().upper()
    nome = re.sub(r"[^A-Z0-9_]+", "_", nome)
    nome = re.sub(r"_+", "_", nome).strip("_")
    return nome or "COLUNA"


def colunas_unicas(cabecalho):
    vistas = {}
    colunas = []

    for nome in cabecalho:
        base = normalizar_nome_coluna(nome)
        contador = vistas.get(base, 0) + 1
        vistas[base] = contador

        if contador == 1:
            colunas.append(base)
        else:
            colunas.append(f"{base}_{contador}")

    return colunas


def configurar_conexao(con):
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -200000")


def tabela_existe(con, tabela):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (tabela,)
    ).fetchone() is not None


def ano_base_da_pasta(pasta):
    encontrado = re.search(r"(20\d{2})", pasta.name)
    return encontrado.group(1) if encontrado else ""


def ano_base_int_da_pasta(pasta):
    ano = ano_base_da_pasta(pasta)
    return int(ano) if ano else None


def importar_csv(con, caminho_csv, tabela, ano_base, lote=20000):
    inicio = time.time()
    print(f"Importando {ano_base}/{caminho_csv.name} -> {tabela}...")

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
                f"(ANO_BASE TEXT, _linha_arquivo INTEGER, {definicao_colunas})"
            )

        placeholders = ", ".join(["?"] * (len(colunas) + 2))
        nomes_colunas = ", ".join(
            [quote_ident("ANO_BASE"), quote_ident("_linha_arquivo")]
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

            buffer.append([ano_base, numero_linha] + linha)

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
    print(
        f"Concluido {ano_base}/{tabela}: {total:,} linhas em {duracao:.1f}s".replace(",", ".")
    )


def criar_indices(con):
    print("Criando indices...")

    indices_por_tabela = {
        "licitacao": [
            """
            CREATE INDEX IF NOT EXISTS idx_licitacao_chave
            ON licitacao (ANO_BASE, CD_ORGAO, NR_LICITACAO, ANO_LICITACAO, CD_TIPO_MODALIDADE)
            """,
        ],
        "item": [
            """
            CREATE INDEX IF NOT EXISTS idx_item_chave
            ON item (ANO_BASE, CD_ORGAO, NR_LICITACAO, ANO_LICITACAO, CD_TIPO_MODALIDADE)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_item_descricao
            ON item (DS_ITEM)
            """,
        ],
        "pessoas": [
            """
            CREATE INDEX IF NOT EXISTS idx_pessoas_documento
            ON pessoas (ANO_BASE, CD_ORGAO, TP_DOCUMENTO, NR_DOCUMENTO)
            """,
        ],
    }

    for tabela, indices in indices_por_tabela.items():
        if tabela_existe(con, tabela):
            for sql in indices:
                con.execute(sql)

    con.commit()


def criar_base_pesquisa(con):
    print("Criando tabela consolidada base_pesquisa...")

    faltantes = [tabela for tabela in ARQUIVOS_BASE_PESQUISA if not tabela_existe(con, tabela)]
    if faltantes:
        lista = ", ".join(faltantes)
        raise RuntimeError(
            "Nao e possivel criar base_pesquisa sem as tabelas base: "
            f"{lista}. Inclua --tabelas base ou prioritarias."
        )

    con.execute("DROP TABLE IF EXISTS base_pesquisa")

    con.execute(
        """
        CREATE TABLE base_pesquisa AS
        SELECT
            i._linha_arquivo AS linha_csv,
            i.ANO_BASE AS ano_base,
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
        FROM item i
        LEFT JOIN licitacao l
            ON l.ANO_BASE = i.ANO_BASE
           AND l.CD_ORGAO = i.CD_ORGAO
           AND l.NR_LICITACAO = i.NR_LICITACAO
           AND l.ANO_LICITACAO = i.ANO_LICITACAO
           AND l.CD_TIPO_MODALIDADE = i.CD_TIPO_MODALIDADE
        LEFT JOIN pessoas p1
            ON p1.ANO_BASE = i.ANO_BASE
           AND p1.CD_ORGAO = i.CD_ORGAO
           AND p1.TP_DOCUMENTO = i.TP_DOCUMENTO
           AND p1.NR_DOCUMENTO = i.NR_DOCUMENTO
        LEFT JOIN pessoas p2
            ON p2.ANO_BASE = i.ANO_BASE
           AND p2.CD_ORGAO = i.CD_ORGAO
           AND p2.TP_DOCUMENTO = i.TP_DOCUMENTO_2
           AND p2.NR_DOCUMENTO = i.NR_DOCUMENTO_2
        LEFT JOIN pessoas p3
            ON p3.ANO_BASE = i.ANO_BASE
           AND p3.CD_ORGAO = i.CD_ORGAO
           AND p3.TP_DOCUMENTO = l.TP_DOCUMENTO_VENCEDOR
           AND p3.NR_DOCUMENTO = l.NR_DOCUMENTO_VENCEDOR
        WHERE i.DS_ITEM IS NOT NULL
          AND TRIM(i.DS_ITEM) <> ''
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_pesquisa_item
        ON base_pesquisa (item)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_pesquisa_homologado
        ON base_pesquisa (valor_unitario, vencedor)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_base_pesquisa_ano
        ON base_pesquisa (ano)
        """
    )
    con.commit()

    total = con.execute("SELECT COUNT(*) FROM base_pesquisa").fetchone()[0]
    print(f"base_pesquisa criada com {total:,} linhas".replace(",", "."))


def validar_arquivos(pasta, tabelas=None):
    tabelas = tabelas or ARQUIVOS_OBRIGATORIOS
    faltantes = [
        nome_arquivo
        for nome_arquivo in tabelas.values()
        if not (pasta / nome_arquivo).exists()
    ]

    if faltantes:
        lista = ", ".join(faltantes)
        raise FileNotFoundError(f"Arquivos obrigatorios nao encontrados: {lista}")


def tabelas_por_argumento(valor):
    valor = (valor or "prioritarias").strip().lower()
    if valor in {"prioritarias", "prioritaria", "padrao", "default"}:
        return ARQUIVOS_PRIORITARIOS
    if valor in {"base", "minima", "minimo"}:
        return ARQUIVOS_BASE_PESQUISA
    if valor == "todas":
        return ARQUIVOS_DISPONIVEIS

    tabelas = {}
    for nome in [parte.strip() for parte in valor.split(",") if parte.strip()]:
        if nome not in ARQUIVOS_DISPONIVEIS:
            disponiveis = ", ".join(sorted(ARQUIVOS_DISPONIVEIS))
            raise ValueError(f"Tabela RAW desconhecida: {nome}. Disponiveis: {disponiveis}")
        tabelas[nome] = ARQUIVOS_DISPONIVEIS[nome]
    if not tabelas:
        raise ValueError("Informe ao menos uma tabela para importar.")
    return tabelas


def resolver_pastas_ano(caminhos, ano_minimo=ANO_MINIMO_PADRAO, anos=None):
    anos_permitidos = {int(ano) for ano in anos} if anos else None
    pastas = []

    for caminho in [Path(p) for p in caminhos]:
        if (caminho / "item.csv").exists():
            candidatas = [caminho]
        else:
            candidatas = sorted(p for p in caminho.iterdir() if p.is_dir())

        for pasta in candidatas:
            ano = ano_base_int_da_pasta(pasta)
            if ano is None:
                continue
            if ano < ano_minimo:
                continue
            if anos_permitidos and ano not in anos_permitidos:
                continue
            pastas.append(pasta)

    if not pastas:
        raise FileNotFoundError("Nenhuma pasta LicitaCon encontrada para os filtros informados.")
    return pastas


def main():
    parser = argparse.ArgumentParser(
        description="Importa os CSVs do LicitaCon para uma base SQLite local."
    )
    parser.add_argument(
        "--pasta",
        nargs="+",
        default=["bases_dados/licitacon_anos"],
        help="Pasta raiz dos anos ou uma ou mais pastas anuais do LicitaCon.",
    )
    parser.add_argument(
        "--saida",
        default=path_str(DEFAULT_RAW_DB_PATH),
        help="Arquivo SQLite que sera criado/atualizado.",
    )
    parser.add_argument(
        "--ano-minimo",
        type=int,
        default=ANO_MINIMO_PADRAO,
        help="Menor ano-base permitido no RAW.",
    )
    parser.add_argument(
        "--anos",
        nargs="*",
        type=int,
        help="Lista opcional de anos especificos para importar.",
    )
    parser.add_argument(
        "--tabelas",
        default="prioritarias",
        help=(
            "Conjunto de tabelas: prioritarias, base, todas ou lista separada por virgula. "
            "Padrao: prioritarias."
        ),
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Atualiza somente os anos selecionados sem apagar os demais anos do RAW.",
    )
    parser.add_argument(
        "--lote",
        type=int,
        default=20000,
        help="Quantidade de linhas por lote de insercao.",
    )

    args = parser.parse_args()

    garantir_diretorios_database()
    tabelas_importacao = tabelas_por_argumento(args.tabelas)
    pastas = resolver_pastas_ano(args.pasta, ano_minimo=args.ano_minimo, anos=args.anos)
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    for pasta in pastas:
        validar_arquivos(pasta, tabelas=tabelas_importacao)

    inicio = time.time()
    con = sqlite3.connect(saida)

    try:
        configurar_conexao(con)

        anos_importados = [ano_base_da_pasta(pasta) for pasta in pastas]
        if args.incremental:
            for tabela in tabelas_importacao:
                if tabela_existe(con, tabela):
                    con.executemany(
                        f"DELETE FROM {quote_ident(tabela)} WHERE ANO_BASE = ?",
                        [(ano,) for ano in anos_importados],
                    )
            con.execute("DROP TABLE IF EXISTS base_pesquisa")
        else:
            for tabela in ARQUIVOS_DISPONIVEIS:
                con.execute(f"DROP TABLE IF EXISTS {quote_ident(tabela)}")
            con.execute("DROP TABLE IF EXISTS base_pesquisa")
        con.commit()

        for pasta in pastas:
            ano_base = ano_base_da_pasta(pasta)

            if not ano_base:
                raise ValueError(f"Nao foi possivel identificar o ano na pasta: {pasta}")

            for tabela, nome_arquivo in tabelas_importacao.items():
                importar_csv(con, pasta / nome_arquivo, tabela, ano_base, lote=args.lote)

        criar_indices(con)
        criar_base_pesquisa(con)

    finally:
        con.close()

    duracao = time.time() - inicio
    print(f"Importacao finalizada em {duracao:.1f}s")
    print(f"Base criada em: {saida.resolve()}")


if __name__ == "__main__":
    main()
