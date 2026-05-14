"""Caminhos padrao da arquitetura de persistencia."""

from pathlib import Path


DATABASE_DIR = Path("database")
RAW_DIR = DATABASE_DIR / "raw"
OPERATIONAL_DIR = DATABASE_DIR / "operational"
APP_DIR = DATABASE_DIR / "app"
MIGRATIONS_DIR = DATABASE_DIR / "migrations"
ETL_DIR = DATABASE_DIR / "etl"

DEFAULT_RAW_DB_PATH = RAW_DIR / "licitacon_raw.sqlite"
DEFAULT_OPERATIONAL_DB_PATH = OPERATIONAL_DIR / "licitacon_search.sqlite"
DEFAULT_PNCP_INDEX_DB_PATH = OPERATIONAL_DIR / "pncp_index.sqlite"
DEFAULT_APP_DB_PATH = APP_DIR / "app.sqlite"

LEGACY_RAW_DB_PATH = Path("licitacon.sqlite")
LEGACY_APP_DB_PATH = Path("pesquisa_precos_app.sqlite")


def garantir_diretorios_database():
    for caminho in (RAW_DIR, OPERATIONAL_DIR, APP_DIR, MIGRATIONS_DIR, ETL_DIR):
        caminho.mkdir(parents=True, exist_ok=True)


def path_str(caminho):
    return str(Path(caminho))
