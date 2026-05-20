import json
import uuid
from pathlib import Path

from flask import session


WORKSPACE_ID_KEY = "pesquisa_lote_workspace_id"
WORKSPACE_DIR = Path("storage/workspaces")


def novo_workspace_id():
    workspace_id = uuid.uuid4().hex
    session[WORKSPACE_ID_KEY] = workspace_id
    session.modified = True
    return workspace_id


def workspace_id_atual():
    workspace_id = session.get(WORKSPACE_ID_KEY)
    if not workspace_id:
        workspace_id = novo_workspace_id()
    return workspace_id


def caminho_workspace(workspace_id=None):
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / f"{workspace_id or workspace_id_atual()}.json"


def carregar_workspace(padrao):
    caminho = caminho_workspace()
    if not caminho.exists():
        return padrao()
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return padrao()


def salvar_workspace_local(workspace):
    caminho = caminho_workspace()
    caminho.write_text(
        json.dumps(workspace, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(caminho)
