from services.internet.whitelist import DEFAULT_ALLOWED_DOMAINS


class InternetSearchClient:
    """Cliente base para busca web controlada.

    Implementacao real deve restringir dominios, respeitar robots/termos de uso
    e aplicar limites de taxa.
    """

    def buscar(self, consulta, *, dominios=None, limite=10):
        dominios = tuple(dominios or DEFAULT_ALLOWED_DOMAINS)
        return []
