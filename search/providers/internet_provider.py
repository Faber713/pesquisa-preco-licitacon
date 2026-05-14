"""Provider Internet preparado para busca controlada futura."""

from search.providers.base_provider import BaseProvider
from services.internet.normalizer import normalizar_resultado_internet
from services.internet.search_client import InternetSearchClient


class InternetProvider(BaseProvider):
    nome = "internet"

    def __init__(self, client=None):
        self.client = client or InternetSearchClient()

    def buscar(self, descricao, *, limite=10, dominios=None, **kwargs):
        resultados = self.client.buscar(descricao, dominios=dominios, limite=limite)
        return [normalizar_resultado_internet(item) for item in resultados]
