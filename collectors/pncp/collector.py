import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from collectors.pncp.checkpoint import (
    obter_checkpoint,
    registrar_log_coleta,
    salvar_checkpoint,
)
from collectors.pncp.normalizer import normalizar_contratacao, normalizar_item
from collectors.pncp.paginator import PNCPPaginator
from config.runtime_settings import PNCP_DEBUG_FOLDER
from database.paths import DEFAULT_PNCP_INDEX_DB_PATH
from services.pncp_client import PNCPClient, PNCPClientError


logger = logging.getLogger("pncp")


class PNCPCollector:
    def __init__(self, *, db_path=DEFAULT_PNCP_INDEX_DB_PATH, client=None, paginator=None):
        self.db_path = Path(db_path)
        self.client = client or PNCPClient()
        self.paginator = paginator or PNCPPaginator(self.client)

    def conectar(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA temp_store = MEMORY")
        return con

    def inicializar_banco(self):
        with self.conectar() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS pncp_contratacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numero_controle_pncp TEXT UNIQUE,
                    cnpj_orgao TEXT,
                    orgao TEXT,
                    municipio TEXT,
                    uf TEXT,
                    ano_compra INTEGER,
                    sequencial_compra TEXT,
                    modalidade TEXT,
                    srp INTEGER,
                    objeto_compra TEXT,
                    informacao_complementar TEXT,
                    data_publicacao TEXT,
                    data_atualizacao TEXT,
                    valor_estimado REAL,
                    valor_homologado REAL,
                    link_origem TEXT,
                    usuario_nome TEXT,
                    amparo_legal_json TEXT,
                    raw_json TEXT,
                    coletado_em TEXT,
                    atualizado_em TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_pncp_contratacoes_orgao
                    ON pncp_contratacoes(cnpj_orgao, ano_compra, sequencial_compra);
                CREATE INDEX IF NOT EXISTS idx_pncp_contratacoes_data
                    ON pncp_contratacoes(data_publicacao);
                CREATE INDEX IF NOT EXISTS idx_pncp_contratacoes_local
                    ON pncp_contratacoes(uf, municipio);

                CREATE TABLE IF NOT EXISTS pncp_itens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contratacao_id INTEGER NOT NULL,
                    numero_item INTEGER,
                    descricao_original TEXT,
                    descricao_normalizada TEXT,
                    unidade TEXT,
                    quantidade REAL,
                    valor_estimado_unitario REAL,
                    valor_estimado_total REAL,
                    valor_homologado_unitario REAL,
                    fornecedor_nome TEXT,
                    fornecedor_cnpj TEXT,
                    categoria TEXT,
                    subcategoria TEXT,
                    raw_json TEXT,
                    hash_dedup TEXT UNIQUE,
                    FOREIGN KEY (contratacao_id) REFERENCES pncp_contratacoes(id)
                );

                CREATE INDEX IF NOT EXISTS idx_pncp_itens_contratacao
                    ON pncp_itens(contratacao_id);
                CREATE INDEX IF NOT EXISTS idx_pncp_itens_hash
                    ON pncp_itens(hash_dedup);

                CREATE TABLE IF NOT EXISTS pncp_coleta_checkpoint (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT NOT NULL,
                    data_inicial TEXT NOT NULL,
                    data_final TEXT NOT NULL,
                    pagina_atual INTEGER NOT NULL DEFAULT 0,
                    total_paginas INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    UNIQUE(endpoint, data_inicial, data_final)
                );

                CREATE TABLE IF NOT EXISTS pncp_coleta_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    endpoint TEXT,
                    pagina INTEGER,
                    status_code INTEGER,
                    tempo_ms REAL,
                    retries INTEGER,
                    mensagem TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS pncp_itens_fts USING fts5(
                    item_id UNINDEXED,
                    descricao_original,
                    descricao_normalizada,
                    categoria,
                    orgao,
                    municipio
                );
                """
            )
            con.commit()

    def salvar_debug(self, endpoint, pagina, payload):
        pasta = Path(PNCP_DEBUG_FOLDER)
        pasta.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = pasta / f"{timestamp}_{endpoint}_pagina_{pagina}.json"
        caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return caminho

    def salvar_debug_itens(self, contratacao_id, payload):
        pasta = Path(PNCP_DEBUG_FOLDER)
        pasta.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = pasta / f"{timestamp}_itens_contratacao_{contratacao_id}.json"
        caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return caminho

    def upsert_contratacao(self, con, registro):
        dados = normalizar_contratacao(registro)
        colunas = list(dados.keys())
        placeholders = ", ".join("?" for _ in colunas)
        updates = ", ".join(
            f"{coluna}=excluded.{coluna}"
            for coluna in colunas
            if coluna not in {"numero_controle_pncp", "coletado_em"}
        )
        con.execute(
            f"""
            INSERT INTO pncp_contratacoes ({", ".join(colunas)})
            VALUES ({placeholders})
            ON CONFLICT(numero_controle_pncp)
            DO UPDATE SET {updates}
            """,
            [dados[coluna] for coluna in colunas],
        )
        row = con.execute(
            "SELECT id FROM pncp_contratacoes WHERE numero_controle_pncp = ?",
            (dados["numero_controle_pncp"],),
        ).fetchone()
        return int(row["id"]), dados

    def upsert_item(self, con, item, contratacao_id, contratacao):
        dados = normalizar_item(item, contratacao_id, contratacao)
        colunas = list(dados.keys())
        placeholders = ", ".join("?" for _ in colunas)
        updates = ", ".join(
            f"{coluna}=excluded.{coluna}"
            for coluna in colunas
            if coluna != "hash_dedup"
        )
        con.execute(
            f"""
            INSERT INTO pncp_itens ({", ".join(colunas)})
            VALUES ({placeholders})
            ON CONFLICT(hash_dedup)
            DO UPDATE SET {updates}
            """,
            [dados[coluna] for coluna in colunas],
        )
        row = con.execute(
            "SELECT id FROM pncp_itens WHERE hash_dedup = ?",
            (dados["hash_dedup"],),
        ).fetchone()
        item_id = int(row["id"])
        con.execute("DELETE FROM pncp_itens_fts WHERE item_id = ?", (str(item_id),))
        con.execute(
            """
            INSERT INTO pncp_itens_fts
            (item_id, descricao_original, descricao_normalizada, categoria, orgao, municipio)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(item_id),
                dados["descricao_original"],
                dados["descricao_normalizada"],
                dados["categoria"],
                contratacao.get("orgao", ""),
                contratacao.get("municipio", ""),
            ),
        )
        return item_id

    def coletar_itens(self, con, contratacao_id, contratacao):
        inicio = time.perf_counter()
        cnpj = contratacao.get("cnpj_orgao")
        ano = contratacao.get("ano_compra")
        sequencial = contratacao.get("sequencial_compra")
        if not cnpj or not ano or not sequencial:
            return 0
        try:
            payload = self.client.listar_itens_compra(cnpj, int(ano), sequencial)
            itens = payload if isinstance(payload, list) else payload.get("data", [])
            self.salvar_debug_itens(contratacao_id, payload)
            for item in itens:
                self.upsert_item(con, item, contratacao_id, contratacao)
            con.commit()
            tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
            logger.info(
                "PNCP itens compra=%s/%s/%s itens=%s tempo_ms=%s",
                cnpj,
                int(ano),
                sequencial,
                len(itens),
                tempo_ms,
            )
            return len(itens)
        except PNCPClientError as erro:
            logger.warning(
                "PNCP itens erro compra=%s/%s/%s erro=%s",
                cnpj,
                ano,
                sequencial,
                erro,
            )
            return 0

    def pagina_inicial(self, con, endpoint, data_inicial, data_final, retomar=True):
        if not retomar:
            return 1
        checkpoint = obter_checkpoint(con, endpoint, data_inicial, data_final)
        if not checkpoint:
            return 1
        if (
            checkpoint["status"] == "ok"
            and int(checkpoint["total_paginas"] or 0) > 0
            and int(checkpoint["pagina_atual"] or 0) >= int(checkpoint["total_paginas"] or 0)
        ):
            return None
        if checkpoint["status"] == "ok":
            return int(checkpoint["pagina_atual"] or 0) + 1
        return max(1, int(checkpoint["pagina_atual"] or 1))

    def coletar(
        self,
        *,
        endpoint,
        data_inicial,
        data_final,
        tamanho_pagina=50,
        codigo_modalidade=8,
        max_paginas=None,
        retomar=True,
        uf=None,
        codigo_municipio_ibge=None,
        cnpj=None,
    ):
        self.inicializar_banco()
        resumo = {
            "endpoint": endpoint,
            "contratacoes": 0,
            "itens": 0,
            "paginas": 0,
            "erros": 0,
        }
        logger.info(
            "PNCP coleta inicio endpoint=%s janela=%s..%s tamanho_pagina=%s",
            endpoint,
            data_inicial,
            data_final,
            tamanho_pagina,
        )
        with self.conectar() as con:
            pagina_inicial = self.pagina_inicial(con, endpoint, data_inicial, data_final, retomar=retomar)
            if pagina_inicial is None:
                logger.info(
                    "PNCP coleta ignorada endpoint=%s janela=%s..%s motivo=checkpoint_completo",
                    endpoint,
                    data_inicial,
                    data_final,
                )
                return resumo
            try:
                paginas = self.paginator.iterar_paginas(
                    endpoint=endpoint,
                    data_inicial=data_inicial,
                    data_final=data_final,
                    pagina_inicial=pagina_inicial,
                    max_paginas=max_paginas,
                    tamanho_pagina=tamanho_pagina,
                    codigo_modalidade=codigo_modalidade,
                    uf=uf,
                    codigo_municipio_ibge=codigo_municipio_ibge,
                    cnpj=cnpj,
                )
                for page in paginas:
                    self.salvar_debug(endpoint, page.pagina, page.payload)
                    resumo["paginas"] += 1
                    resumo["contratacoes"] += len(page.registros)
                    logger.info(
                        "PNCP pagina pagina=%s total_paginas=%s registros=%s tempo_ms=%s retry=%s",
                        page.pagina,
                        page.total_paginas,
                        len(page.registros),
                        page.tempo_ms,
                        page.retries,
                    )
                    registrar_log_coleta(
                        con,
                        endpoint=endpoint,
                        pagina=page.pagina,
                        status_code=200,
                        tempo_ms=page.tempo_ms,
                        retries=page.retries,
                        mensagem=f"registros={len(page.registros)} total_paginas={page.total_paginas}",
                    )
                    for registro in page.registros:
                        contratacao_id, contratacao = self.upsert_contratacao(con, registro)
                        resumo["itens"] += self.coletar_itens(con, contratacao_id, contratacao)
                    salvar_checkpoint(
                        con,
                        endpoint=endpoint,
                        data_inicial=data_inicial,
                        data_final=data_final,
                        pagina_atual=page.pagina,
                        total_paginas=page.total_paginas,
                        status="ok",
                    )
                    logger.info(
                        "PNCP checkpoint endpoint=%s pagina=%s status=ok",
                        endpoint,
                        page.pagina,
                    )
            except PNCPClientError as erro:
                resumo["erros"] += 1
                registrar_log_coleta(
                    con,
                    endpoint=endpoint,
                    pagina=pagina_inicial,
                    status_code=0,
                    tempo_ms=0,
                    retries=0,
                    mensagem=str(erro),
                )
                salvar_checkpoint(
                    con,
                    endpoint=endpoint,
                    data_inicial=data_inicial,
                    data_final=data_final,
                    pagina_atual=pagina_inicial,
                    total_paginas=0,
                    status="erro",
                )
                logger.warning(
                    "PNCP checkpoint endpoint=%s pagina=%s status=erro erro=%s",
                    endpoint,
                    pagina_inicial,
                    erro,
                )
        logger.info(
            "PNCP coleta fim endpoint=%s paginas=%s contratacoes=%s itens=%s erros=%s",
            endpoint,
            resumo["paginas"],
            resumo["contratacoes"],
            resumo["itens"],
            resumo["erros"],
        )
        return resumo
