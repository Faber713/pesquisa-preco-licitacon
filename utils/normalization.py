import re
import unicodedata

from config.app_settings import PALAVRAS_FRACAS


CORRECOES_NORMALIZACAO = {
    "amper metro": "amperimetro",
    "anal gico": "analogico",
    "anal gica": "analogica",
    "lumin ria": "luminaria",
    "p blica": "publica",
    "el trico": "eletrico",
    "el trica": "eletrica",
    "rel ": "rele ",
    "f cio": "facil",
    "a o": "aco",
}


def remover_acentos(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return texto.encode("ascii", "ignore").decode("utf-8")


def colapsar_espacos(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def normalizar_texto(texto):
    texto = remover_acentos(texto).lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = colapsar_espacos(texto)
    for errado, certo in CORRECOES_NORMALIZACAO.items():
        texto = texto.replace(errado, certo)
    return colapsar_espacos(texto)


def tokens_relevantes(texto, stopwords=None, tamanho_minimo=3):
    stopwords = set(PALAVRAS_FRACAS).union(stopwords or set())
    return [
        token
        for token in normalizar_texto(texto).split()
        if len(token) >= tamanho_minimo and token not in stopwords
    ]

