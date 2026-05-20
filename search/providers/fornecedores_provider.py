"""Provider de fornecedores reservado para evolucao futura."""

from search.providers.base_provider import BaseProvider


class FornecedoresProvider(BaseProvider):
    nome = "fornecedores"
    confiabilidade = 0.75

    def buscar(self, *args, **kwargs):
        return []
