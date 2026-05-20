"""Provider Compras.gov reservado para integracao incremental."""

from search.providers.base_provider import BaseProvider


class ComprasGovProvider(BaseProvider):
    nome = "comprasgov"
    confiabilidade = 0.90

    def buscar(self, *args, **kwargs):
        return []
