import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta


def normalizar_orgao(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto.replace("J IA", "JOIA").replace("J OIA", "JOIA")


def gerar_item_uid(descricao, quantidade=""):
    base = f"{normalizar_orgao(descricao)}|{str(quantidade or '').strip()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def gerar_resultado_uid(resultado, item_uid=""):
    base = "|".join(
        str(resultado.get(chave, "") or "")
        for chave in [
            "orgao",
            "descricao",
            "valor_unitario",
            "vencedor",
            "processo",
            "modalidade",
            "ano",
        ]
    )
    return hashlib.sha1(f"{item_uid}|{base}".encode("utf-8")).hexdigest()[:16]


def orgao_equivalente(origem, orgao_resultado):
    origem_norm = normalizar_orgao(origem)
    orgao_norm = normalizar_orgao(orgao_resultado)
    if not origem_norm or not orgao_norm:
        return False

    termos_origem = {
        origem_norm,
        origem_norm.replace("PREFEITURA MUNICIPAL DE ", "").strip(),
        origem_norm.replace("PM DE ", "").strip(),
    }
    termos_origem.update({"JOIA", "PREFEITURA MUNICIPAL DE JOIA", "PM DE JOIA"})
    termos_origem = {termo for termo in termos_origem if termo}
    return any(termo in orgao_norm for termo in termos_origem)


def filtrar_orgao_origem(resultados, orgao_origem, ativo):
    if not ativo:
        return list(resultados), 0

    filtrados = [
        resultado
        for resultado in resultados
        if not orgao_equivalente(orgao_origem, resultado.get("orgao", ""))
    ]
    return filtrados, len(resultados) - len(filtrados)


def _parse_data(valor):
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def periodo_para_datas(tipo, data_inicial="", data_final=""):
    hoje = date.today()
    if tipo == "6m":
        return hoje - timedelta(days=183), hoje
    if tipo == "12m":
        return hoje - timedelta(days=365), hoje
    if tipo == "personalizado":
        return _parse_data(data_inicial), _parse_data(data_final)
    return None, None


def filtrar_periodo_resultados(resultados, data_inicial, data_final):
    if not data_inicial and not data_final:
        return list(resultados), 0

    filtrados = []
    removidos = 0
    for resultado in resultados:
        data_resultado = _parse_data(
            resultado.get("data_homologacao")
            or resultado.get("dt_homologacao")
            or resultado.get("data")
            or resultado.get("ano")
        )
        if not data_resultado:
            removidos += 1
            continue
        if data_inicial and data_resultado < data_inicial:
            removidos += 1
            continue
        if data_final and data_resultado > data_final:
            removidos += 1
            continue
        filtrados.append(resultado)
    return filtrados, removidos


def preparar_resultados(resultados, item_uid):
    preparados = []
    for resultado in resultados:
        copia = dict(resultado)
        copia["resultado_uid"] = copia.get("resultado_uid") or gerar_resultado_uid(copia, item_uid)
        preparados.append(copia)
    return preparados
