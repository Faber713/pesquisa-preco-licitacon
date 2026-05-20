import hashlib

from utils.util import normalizar


def hash_item_pncp(numero_controle_pncp, numero_item, descricao):
    base = "|".join(
        [
            normalizar(numero_controle_pncp or ""),
            str(numero_item or "").strip(),
            normalizar(descricao or ""),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

