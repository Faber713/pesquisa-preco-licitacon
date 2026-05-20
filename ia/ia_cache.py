import hashlib
import json
import sqlite3
import time
from pathlib import Path

from utils.util import normalizar


CACHE_PATH = Path("database/app/ia_cache.sqlite")


def hash_descricao(descricao):
    texto = normalizar(descricao or "")
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def conectar_cache():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cache_ia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash_descricao TEXT UNIQUE NOT NULL,
            descricao_original TEXT NOT NULL,
            resultado_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            ultimo_uso REAL NOT NULL
        )
        """
    )
    con.commit()
    return con


def obter_cache_ia(descricao):
    chave = hash_descricao(descricao)
    with conectar_cache() as con:
        row = con.execute(
            """
            SELECT resultado_json
            FROM cache_ia
            WHERE hash_descricao = ?
            """,
            (chave,),
        ).fetchone()
        if not row:
            return None
        con.execute(
            "UPDATE cache_ia SET ultimo_uso = ? WHERE hash_descricao = ?",
            (time.time(), chave),
        )
        con.commit()
    return json.loads(row[0])


def salvar_cache_ia(descricao, resultado):
    chave = hash_descricao(descricao)
    agora = time.time()
    with conectar_cache() as con:
        con.execute(
            """
            INSERT INTO cache_ia
            (hash_descricao, descricao_original, resultado_json, created_at, ultimo_uso)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(hash_descricao) DO UPDATE SET
                resultado_json = excluded.resultado_json,
                ultimo_uso = excluded.ultimo_uso
            """,
            (
                chave,
                descricao or "",
                json.dumps(resultado, ensure_ascii=False),
                agora,
                agora,
            ),
        )
        con.commit()


def cache_ia_ok():
    try:
        with conectar_cache() as con:
            con.execute("SELECT 1 FROM cache_ia LIMIT 1").fetchone()
        return True
    except Exception:
        return False
