"""Migra o banco APP legado da raiz para database/app/app.sqlite."""

import argparse
import shutil
from pathlib import Path

from database.paths import DEFAULT_APP_DB_PATH, LEGACY_APP_DB_PATH, garantir_diretorios_database, path_str


def migrar_app_db(origem=LEGACY_APP_DB_PATH, destino=DEFAULT_APP_DB_PATH, sobrescrever=False):
    origem = Path(origem)
    destino = Path(destino)

    if not origem.exists():
        raise FileNotFoundError(f"Banco APP legado nao encontrado: {origem}")
    if destino.exists() and not sobrescrever:
        raise FileExistsError(
            f"Destino ja existe: {destino}. Use --sobrescrever se quiser substituir."
        )

    garantir_diretorios_database()
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)
    return destino


def main():
    parser = argparse.ArgumentParser(
        description="Copia um banco APP legado para database/app/app.sqlite."
    )
    parser.add_argument("--origem", default=path_str(LEGACY_APP_DB_PATH))
    parser.add_argument("--destino", default=path_str(DEFAULT_APP_DB_PATH))
    parser.add_argument("--sobrescrever", action="store_true")
    args = parser.parse_args()

    destino = migrar_app_db(args.origem, args.destino, sobrescrever=args.sobrescrever)
    print(f"Banco APP migrado para: {destino.resolve()}")


if __name__ == "__main__":
    main()
