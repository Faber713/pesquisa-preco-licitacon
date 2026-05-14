DEFAULT_ALLOWED_DOMAINS = (
    "gov.br",
    "compras.gov.br",
    "pncp.gov.br",
)


def dominio_permitido(url, dominios=None):
    dominios = tuple(dominios or DEFAULT_ALLOWED_DOMAINS)
    texto = str(url or "").lower()
    return any(dominio.lower() in texto for dominio in dominios)
