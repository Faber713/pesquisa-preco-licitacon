import os
from dataclasses import dataclass
from pathlib import Path

from database.paths import DEFAULT_OPERATIONAL_DB_PATH, DEFAULT_RAW_DB_PATH, path_str

SEARCH_DB_MODES = {"auto", "raw", "operational"}


@dataclass(frozen=True)
class SearchDbConfig:
    mode: str
    raw_path: str
    operational_path: str


def carregar_search_db_config(getter=None):
    getter = getter or os.getenv
    mode = str(getter("SEARCH_DB_MODE", "auto") or "auto").strip().lower()
    if mode not in SEARCH_DB_MODES:
        mode = "auto"

    raw_path = str(
        getter("LICITACON_SQLITE_PATH", path_str(DEFAULT_RAW_DB_PATH))
        or path_str(DEFAULT_RAW_DB_PATH)
    )
    operational_path = str(
        getter("SEARCH_DB_PATH", path_str(DEFAULT_OPERATIONAL_DB_PATH))
        or path_str(DEFAULT_OPERATIONAL_DB_PATH)
    )

    return SearchDbConfig(
        mode=mode,
        raw_path=raw_path,
        operational_path=operational_path,
    )


def caminho_existe(caminho):
    return Path(caminho).exists()
