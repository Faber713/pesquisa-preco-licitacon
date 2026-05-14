from storage.app_storage import CAMINHO_APP_DB, inicializar_app_db


if __name__ == "__main__":
    inicializar_app_db()
    print(f"Banco APP inicializado em: {CAMINHO_APP_DB}")
