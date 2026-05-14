from search.models import item_valido
from search.providers.pncp_provider import PNCPProvider


class SearchManager:
    def __init__(self, providers=None):
        self.providers = providers or {
            "pncp": PNCPProvider(),
        }

    def buscar(self, descricao, fontes=None, **kwargs):
        fontes = [fonte.lower() for fonte in (fontes or self.providers.keys())]
        resultados = []
        erros = {}

        for fonte in fontes:
            provider = self.providers.get(fonte)
            if not provider:
                erros[fonte] = "Provider nao registrado."
                continue
            try:
                resultados.extend(
                    resultado
                    for resultado in provider.buscar(descricao, **kwargs)
                    if item_valido(resultado)
                )
            except Exception as erro:
                erros[fonte] = str(erro)

        return {
            "resultados": sorted(resultados, key=lambda r: r.get("score", 0), reverse=True),
            "erros": erros,
        }
