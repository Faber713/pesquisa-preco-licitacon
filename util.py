import pandas as pd
import unicodedata
import re

from config import PALAVRAS_FRACAS


# =========================
# NORMALIZAÇÃO
# =========================

def normalizar(texto):
    texto = str(texto).lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    correcoes = {
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

    for errado, certo in correcoes.items():
        texto = texto.replace(errado, certo)

    return texto


def lista_normalizada(lista):
    return [normalizar(x) for x in lista if normalizar(x)]


# =========================
# ARQUIVO
# =========================

def escolher_arquivo():
    """Compatibilidade com a versao desktop.

    No Streamlit, os arquivos sao enviados por st.file_uploader em app_web.py.
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
