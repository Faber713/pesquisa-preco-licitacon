"""Provider LicitaCon preparado para encapsular a busca SQLite atual."""

from search.providers.base_provider import BaseProvider


class LicitaConProvider(BaseProvider):
    nome = "licitacon"
