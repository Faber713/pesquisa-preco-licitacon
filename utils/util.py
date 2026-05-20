import pandas as pd
import unicodedata
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from config.app_settings import PALAVRAS_FRACAS
from utils.normalization import normalizar_texto


# =========================
# NORMALIZAÇÃO
# =========================

def normalizar(texto):
    return normalizar_texto(texto)


def lista_normalizada(lista):
    return [normalizar(x) for x in lista if normalizar(x)]


# =========================
# ARQUIVO
# =========================

def escolher_arquivo():
    """Compatibilidade com a versao desktop.

    Na aplicacao Flask, uploads sao tratados pelas rotas e services de `web/`.
    Manter esta funcao retornando None evita depender de tkinter no ambiente web.
    """
    return None


# =========================
# CONVERSÃO
# =========================

def converter_numero(valor):
    try:
        if valor is None:
            return None

        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            if pd.isna(valor):
                return None
            return float(valor)

        texto = str(valor).replace("R$", "").strip()

        if texto == "" or texto.lower() == "nan":
            return None

        texto = re.sub(r"[^0-9,.\-]", "", texto)

        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif "." in texto:
            partes = texto.split(".")
            if len(partes) > 2:
                texto = "".join(partes[:-1]) + "." + partes[-1]
            elif len(partes[-1]) == 3 and len(partes[0]) > 0:
                texto = texto.replace(".", "")

        return float(texto)

    except:
        return None


def formatar_percentual(valor):
    numero = converter_numero(valor)
    if numero is None:
        return "-"

    try:
        decimal = Decimal(str(numero)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return "-"

    texto = format(decimal, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto


def formatar_moeda_br(valor):
    numero = converter_numero(valor)
    if numero is None:
        return "-"

    try:
        decimal = Decimal(str(numero)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return "-"

    negativo = decimal < 0
    decimal = abs(decimal)
    inteiro, centavos = f"{decimal:.2f}".split(".")
    partes = []
    while inteiro:
        partes.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    texto = ".".join(partes) + "," + centavos
    return f"{'-' if negativo else ''}R$ {texto}"


# =========================
# CSV
# =========================

def pegar_coluna(row, nomes):
    for nome in nomes:
        if nome in row:
            valor = row.get(nome, "")

            if pd.isna(valor):
                return ""

            return valor

    return ""


# =========================
# COMPARAÇÃO DE TERMOS
# =========================

def contem_termo(texto_norm, termo_norm):
    if not termo_norm:
        return False

    if " " in termo_norm:
        return termo_norm in texto_norm

    return re.search(rf"\b{re.escape(termo_norm)}\b", texto_norm) is not None


def radical_simples(palavra):
    palavra = normalizar(palavra)

    finais = [
        "oes", "aes", "ais", "eis", "ois",
        "res", "ras", "ros",
        "icas", "icos", "ica", "ico",
        "adas", "ados", "ada", "ado",
        "as", "os", "es", "a", "o"
    ]

    for final in finais:
        if len(palavra) > 6 and palavra.endswith(final):
            return palavra[:-len(final)]

    return palavra


def termos_compativeis(termo, texto_norm):
    termo_norm = normalizar(termo)

    if not termo_norm:
        return False

    if contem_termo(texto_norm, termo_norm):
        return True

    rad = radical_simples(termo_norm)

    if len(rad) >= 6:
        palavras = texto_norm.split()

        for p in palavras:
            rp = radical_simples(p)
            if len(rp) < 5:
                continue

            if rp.startswith(rad) or rad.startswith(rp):
                return True

    return False


# =========================
# PALAVRAS FORTES
# =========================

def palavras_fortes(texto):
    extras_fracas = {
        "bloco", "blocos", "kit", "conjunto",
        "peca", "pecas", "item", "un", "und",
        "rele", "sensor", "chave", "dispositivo",
        "eletrico", "eletrica", "eletricos", "eletricas",
        "aparelho", "equipamento", "ferramenta", "maquina", "servico",
        "analogo", "analogico", "digital", "automatico", "manual"
    }

    fracas = set(PALAVRAS_FRACAS).union(extras_fracas)

    texto_norm = normalizar(texto)
    palavras = texto_norm.split()

    fortes = []

    for p in palavras:
        if len(p) >= 4 and p not in fracas:
            fortes.append(p)

    return list(dict.fromkeys(fortes))


# =========================
# JAVASCRIPT / HTML
# =========================

def preparar_js(texto):
    texto = str(texto)

    texto = texto.replace("\\", "\\\\")
    texto = texto.replace("'", "\\'")
    texto = texto.replace('"', '\\"')
    texto = texto.replace("\n", "\\n")
    texto = texto.replace("\r", "")

    return texto
