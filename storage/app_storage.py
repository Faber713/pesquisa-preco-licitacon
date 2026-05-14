import os
import json
import sqlite3
from pathlib import Path

from database.paths import DEFAULT_APP_DB_PATH, garantir_diretorios_database, path_str
from search.fontes_preco import agora_iso


CAMINHO_APP_DB = Path(os.getenv("APP_DB_PATH", path_str(DEFAULT_APP_DB_PATH)))


def conectar_app_db():
    garantir_diretorios_database()
    CAMINHO_APP_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CAMINHO_APP_DB)
    con.row_factory = sqlite3.Row
    return con


def inicializar_app_db():
    with conectar_app_db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS fornecedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cpf_cnpj TEXT,
                email TEXT,
                telefone TEXT,
                municipio TEXT,
                uf TEXT,
                categorias TEXT,
                observacoes TEXT,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cotacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornecedor_id INTEGER,
                item_pesquisado TEXT NOT NULL,
                data_solicitacao TEXT,
                data_resposta TEXT,
                valor_unitario REAL,
                valor_total REAL,
                quantidade REAL,
                unidade TEXT,
                evidencia TEXT,
                status TEXT NOT NULL DEFAULT 'solicitada',
                criado_em TEXT NOT NULL,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id)
            );

            CREATE TABLE IF NOT EXISTS pesquisas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                descricao TEXT NOT NULL,
                fontes TEXT,
                metodologia TEXT,
                resultado_json TEXT,
                responsavel TEXT NOT NULL,
                data_pesquisa TEXT NOT NULL,
                parametros TEXT,
                metodo_escolhido TEXT,
                justificativas TEXT,
                created_at TEXT,
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fontes_preco (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pesquisa_id INTEGER,
                origem TEXT NOT NULL,
                descricao TEXT,
                valor_unitario REAL,
                valor_total REAL,
                quantidade REAL,
                unidade TEXT,
                data_referencia TEXT,
                fornecedor_nome TEXT,
                fornecedor_cnpj TEXT,
                orgao TEXT,
                municipio TEXT,
                uf TEXT,
                link TEXT,
                evidencia TEXT,
                score REAL,
                status_validacao TEXT,
                motivos_alerta TEXT,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (pesquisa_id) REFERENCES pesquisas(id)
            );

            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'admin',
                ativo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                criado_em TEXT NOT NULL,
                ultimo_login TEXT
            );

            CREATE TABLE IF NOT EXISTS auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                acao TEXT NOT NULL,
                entidade TEXT,
                entidade_id TEXT,
                dados_json TEXT,
                ip TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS favoritos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                consulta_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        _migrar_schema_app(con)


def _colunas_tabela(con, tabela):
    return {row["name"] for row in con.execute(f"PRAGMA table_info({tabela})").fetchall()}


def _adicionar_coluna(con, tabela, coluna, definicao):
    if coluna not in _colunas_tabela(con, tabela):
        con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def _migrar_schema_app(con):
    _adicionar_coluna(con, "usuarios", "created_at", "TEXT")
    _adicionar_coluna(con, "pesquisas", "usuario_id", "INTEGER")
    _adicionar_coluna(con, "pesquisas", "fontes", "TEXT")
    _adicionar_coluna(con, "pesquisas", "metodologia", "TEXT")
    _adicionar_coluna(con, "pesquisas", "resultado_json", "TEXT")
    _adicionar_coluna(con, "pesquisas", "created_at", "TEXT")
    agora = agora_iso()
    con.execute("UPDATE usuarios SET created_at = COALESCE(created_at, criado_em, ?)", (agora,))
    con.execute("UPDATE pesquisas SET created_at = COALESCE(created_at, criado_em, ?)", (agora,))
    con.commit()


def _json_dumps(valor):
    return json.dumps(valor or {}, ensure_ascii=False, default=str)


def cadastrar_fornecedor(dados):
    with conectar_app_db() as con:
        con.execute(
            """
            INSERT INTO fornecedores
            (nome, cpf_cnpj, email, telefone, municipio, uf, categorias, observacoes, ativo, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dados.get("nome", "").strip(),
                dados.get("cpf_cnpj", "").strip(),
                dados.get("email", "").strip(),
                dados.get("telefone", "").strip(),
                dados.get("municipio", "").strip(),
                dados.get("uf", "").strip().upper(),
                dados.get("categorias", "").strip(),
                dados.get("observacoes", "").strip(),
                1 if dados.get("ativo", True) else 0,
                agora_iso(),
            ),
        )


def listar_fornecedores(ativos=True):
    with conectar_app_db() as con:
        sql = "SELECT * FROM fornecedores"
        params = []
        if ativos:
            sql += " WHERE ativo = ?"
            params.append(1)
        sql += " ORDER BY nome"
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def cadastrar_cotacao(dados):
    with conectar_app_db() as con:
        con.execute(
            """
            INSERT INTO cotacoes
            (fornecedor_id, item_pesquisado, data_solicitacao, data_resposta,
             valor_unitario, valor_total, quantidade, unidade, evidencia, status, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dados.get("fornecedor_id"),
                dados.get("item_pesquisado", "").strip(),
                dados.get("data_solicitacao", "").strip(),
                dados.get("data_resposta", "").strip(),
                dados.get("valor_unitario"),
                dados.get("valor_total"),
                dados.get("quantidade"),
                dados.get("unidade", "").strip(),
                dados.get("evidencia", "").strip(),
                dados.get("status", "solicitada"),
                agora_iso(),
            ),
        )


def listar_cotacoes_por_descricao(descricao):
    termo = f"%{descricao.strip()}%"
    with conectar_app_db() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT c.*, f.nome AS fornecedor_nome, f.cpf_cnpj, f.municipio, f.uf
                FROM cotacoes c
                LEFT JOIN fornecedores f ON f.id = c.fornecedor_id
                WHERE c.item_pesquisado LIKE ?
                ORDER BY COALESCE(c.data_resposta, c.data_solicitacao, c.criado_em) DESC
                LIMIT 50
                """,
                (termo,),
            ).fetchall()
        ]


def contar_usuarios():
    with conectar_app_db() as con:
        row = con.execute("SELECT COUNT(*) AS total FROM usuarios").fetchone()
        return int(row["total"] or 0)


def listar_usuarios():
    with conectar_app_db() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT id, nome, email, perfil, ativo, criado_em, ultimo_login
                FROM usuarios
                ORDER BY nome, email
                """
            ).fetchall()
        ]


def criar_usuario(nome, email, senha_hash, perfil="admin", ativo=True):
    with conectar_app_db() as con:
        agora = agora_iso()
        cur = con.execute(
            """
            INSERT INTO usuarios
            (nome, email, senha_hash, perfil, ativo, created_at, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome.strip(),
                email.strip().lower(),
                senha_hash,
                perfil.strip() or "admin",
                1 if ativo else 0,
                agora,
                agora,
            ),
        )
        return cur.lastrowid


def buscar_usuario_por_email(email):
    with conectar_app_db() as con:
        row = con.execute(
            "SELECT * FROM usuarios WHERE lower(email) = lower(?) LIMIT 1",
            (email.strip(),),
        ).fetchone()
        return dict(row) if row else None


def buscar_usuario_por_id(usuario_id):
    with conectar_app_db() as con:
        row = con.execute("SELECT * FROM usuarios WHERE id = ? LIMIT 1", (usuario_id,)).fetchone()
        return dict(row) if row else None


def atualizar_usuario(usuario_id, nome, email, perfil, ativo):
    with conectar_app_db() as con:
        con.execute(
            """
            UPDATE usuarios
            SET nome = ?, email = ?, perfil = ?, ativo = ?
            WHERE id = ?
            """,
            (
                nome.strip(),
                email.strip().lower(),
                perfil.strip() or "usuario",
                1 if ativo else 0,
                usuario_id,
            ),
        )


def atualizar_senha_usuario(usuario_id, senha_hash):
    with conectar_app_db() as con:
        con.execute(
            "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
            (senha_hash, usuario_id),
        )


def registrar_login_usuario(usuario_id):
    with conectar_app_db() as con:
        con.execute(
            "UPDATE usuarios SET ultimo_login = ? WHERE id = ?",
            (agora_iso(), usuario_id),
        )


def registrar_auditoria(usuario_id, acao, entidade="", entidade_id="", dados=None, ip=""):
    with conectar_app_db() as con:
        con.execute(
            """
            INSERT INTO auditoria
            (usuario_id, acao, entidade, entidade_id, dados_json, ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usuario_id,
                acao,
                entidade,
                str(entidade_id or ""),
                _json_dumps(dados),
                ip or "",
                agora_iso(),
            ),
        )


def listar_auditoria(limite=200, usuario_id=None):
    with conectar_app_db() as con:
        params = []
        sql = """
            SELECT a.*, u.nome AS usuario_nome, u.email AS usuario_email
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
        """
        if usuario_id:
            sql += " WHERE a.usuario_id = ?"
            params.append(usuario_id)
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        params.append(int(limite))
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def salvar_pesquisa_usuario(usuario_id, descricao, fontes, metodologia, resultado):
    with conectar_app_db() as con:
        cur = con.execute(
            """
            INSERT INTO pesquisas
            (usuario_id, descricao, fontes, metodologia, resultado_json, responsavel,
             data_pesquisa, parametros, metodo_escolhido, justificativas, created_at, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, date('now'), ?, ?, ?, ?, ?)
            """,
            (
                usuario_id,
                descricao,
                _json_dumps(fontes),
                metodologia,
                _json_dumps(resultado),
                "",
                _json_dumps({}),
                metodologia,
                _json_dumps({}),
                agora_iso(),
                agora_iso(),
            ),
        )
        return cur.lastrowid


def listar_pesquisas_usuario(usuario_id, limite=100):
    with conectar_app_db() as con:
        params = []
        sql = "SELECT * FROM pesquisas"
        if usuario_id:
            sql += " WHERE usuario_id = ?"
            params.append(usuario_id)
        sql += " ORDER BY COALESCE(created_at, criado_em) DESC LIMIT ?"
        params.append(int(limite))
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def salvar_favorito(usuario_id, nome, consulta):
    with conectar_app_db() as con:
        cur = con.execute(
            """
            INSERT INTO favoritos (usuario_id, nome, consulta_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (usuario_id, nome, _json_dumps(consulta), agora_iso()),
        )
        return cur.lastrowid


def salvar_pesquisa(descricao, responsavel, parametros, metodo_escolhido, justificativas, fontes):
    with conectar_app_db() as con:
        cur = con.execute(
            """
            INSERT INTO pesquisas
            (descricao, responsavel, data_pesquisa, parametros, metodo_escolhido, justificativas, criado_em)
            VALUES (?, ?, date('now'), ?, ?, ?, ?)
            """,
            (descricao, responsavel, parametros, metodo_escolhido, justificativas, agora_iso()),
        )
        pesquisa_id = cur.lastrowid

        for fonte in fontes:
            con.execute(
                """
                INSERT INTO fontes_preco
                (pesquisa_id, origem, descricao, valor_unitario, valor_total, quantidade, unidade,
                 data_referencia, fornecedor_nome, fornecedor_cnpj, orgao, municipio, uf, link,
                 evidencia, score, status_validacao, motivos_alerta, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pesquisa_id,
                    fonte.get("origem"),
                    fonte.get("descricao"),
                    fonte.get("valor_unitario"),
                    fonte.get("valor_total"),
                    fonte.get("quantidade"),
                    fonte.get("unidade"),
                    fonte.get("data_referencia"),
                    fonte.get("fornecedor_nome"),
                    fonte.get("fornecedor_cnpj"),
                    fonte.get("orgao"),
                    fonte.get("municipio"),
                    fonte.get("uf"),
                    fonte.get("link"),
                    fonte.get("evidencia"),
                    fonte.get("score"),
                    fonte.get("status_validacao"),
                    fonte.get("motivos_alerta"),
                    agora_iso(),
                ),
            )

        return pesquisa_id
