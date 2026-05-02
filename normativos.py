from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean, median
import re
import zlib

from util import converter_numero


@dataclass(frozen=True)
class PerfilNormativo:
    codigo: str
    nome: str
    base_legal: tuple[str, ...]
    prazo_precos_dias: int
    minimo_precos: int
    permite_menos_tres_com_justificativa: bool
    exige_evidencias: bool = True
    observacoes: str = ""


PERFIS_NORMATIVOS = {
    "joia_rs_5337": PerfilNormativo(
        codigo="joia_rs_5337",
        nome="Joia/RS - Decretos 5.337/2023 e 5.531/2024",
        base_legal=(
            "Decreto Municipal de Joia/RS nº 5.337/2023",
            "Decreto Municipal de Joia/RS nº 5.531/2024",
            "Lei Federal nº 14.133/2021",
        ),
        prazo_precos_dias=183,
        minimo_precos=3,
        permite_menos_tres_com_justificativa=True,
        observacoes=(
            "Perfil calibrado para pesquisa de precos de bens e servicos em geral no Municipio de Joia/RS. "
            "O Decreto 5.531/2024 e considerado para Registro de Precos, vantajosidade e comparacao com mercado."
        ),
    ),
    "lei_14133_padrao": PerfilNormativo(
        codigo="lei_14133_padrao",
        nome="Padrao geral - Lei 14.133/2021",
        base_legal=("Lei Federal nº 14.133/2021",),
        prazo_precos_dias=365,
        minimo_precos=3,
        permite_menos_tres_com_justificativa=True,
        observacoes=(
            "Perfil generico para municipios sem decreto local cadastrado. "
            "Os parametros devem ser revisados pela equipe responsavel antes de anexar ao processo."
        ),
    ),
}


def registrar_perfil_normativo(perfil):
    PERFIS_NORMATIVOS[perfil.codigo] = perfil


def perfil_para_dict(perfil):
    return {
        "codigo": perfil.codigo,
        "nome": perfil.nome,
        "base_legal": list(perfil.base_legal),
        "prazo_precos_dias": perfil.prazo_precos_dias,
        "minimo_precos": perfil.minimo_precos,
        "permite_menos_tres_com_justificativa": perfil.permite_menos_tres_com_justificativa,
        "exige_evidencias": perfil.exige_evidencias,
        "observacoes": perfil.observacoes,
    }


def perfil_de_dict(dados):
    return PerfilNormativo(
        codigo=dados["codigo"],
        nome=dados["nome"],
        base_legal=tuple(dados.get("base_legal", [])),
        prazo_precos_dias=int(dados.get("prazo_precos_dias", 183)),
        minimo_precos=int(dados.get("minimo_precos", 3)),
        permite_menos_tres_com_justificativa=bool(
            dados.get("permite_menos_tres_com_justificativa", True)
        ),
        exige_evidencias=bool(dados.get("exige_evidencias", True)),
        observacoes=dados.get("observacoes", ""),
    )


def obter_perfil_normativo(codigo=None):
    return PERFIS_NORMATIVOS.get(codigo or "joia_rs_5337", PERFIS_NORMATIVOS["joia_rs_5337"])


def listar_perfis_normativos():
    return list(PERFIS_NORMATIVOS.values())


def _obj_pdf(data, numero):
    match = re.search(rb"\b%d\s+0\s+obj(.*?)endobj" % numero, data, re.S)
    return match.group(1) if match else b""


def _stream_pdf(body):
    if b"stream" not in body:
        return b""

    stream = body.split(b"stream", 1)[1].rsplit(b"endstream", 1)[0].strip(b"\r\n")
    if b"/FlateDecode" in body:
        try:
            return zlib.decompress(stream)
        except Exception:
            return b""
    return stream


def _parse_cmap(cmap_bytes):
    texto = cmap_bytes.decode("latin1", errors="ignore")
    mapa = {}

    for match in re.finditer(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>\s*\[(.*?)\]", texto, re.S):
        inicio = int(match.group(1), 16)
        valores = re.findall(r"<([0-9A-Fa-f]+)>", match.group(3))
        for indice, valor in enumerate(valores):
            mapa[inicio + indice] = "".join(
                chr(int(valor[pos:pos + 4], 16))
                for pos in range(0, len(valor), 4)
            )

    for match in re.finditer(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]+)>", texto):
        inicio = int(match.group(1), 16)
        fim = int(match.group(2), 16)
        destino = int(match.group(3), 16)
        for codigo in range(inicio, fim + 1):
            mapa.setdefault(codigo, chr(destino + (codigo - inicio)))

    for match in re.finditer(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]+)>", texto):
        codigo = int(match.group(1), 16)
        valor = match.group(2)
        mapa.setdefault(
            codigo,
            "".join(chr(int(valor[pos:pos + 4], 16)) for pos in range(0, len(valor), 4)),
        )

    return mapa


def _decode_hex_pdf(hex_texto, cmap):
    hex_texto = re.sub(r"\s+", "", hex_texto)
    saida = []
    passo = 4 if cmap else 2
    for pos in range(0, len(hex_texto), passo):
        try:
            codigo = int(hex_texto[pos:pos + passo], 16)
        except ValueError:
            continue
        if cmap:
            saida.append(cmap.get(codigo, ""))
        else:
            saida.append(chr(codigo))
    return "".join(saida)


def _decode_literal_pdf(valor):
    valor = valor.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    valor = valor.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")

    def trocar_octal(match):
        try:
            return chr(int(match.group(1), 8))
        except ValueError:
            return ""

    return re.sub(r"\\([0-7]{1,3})", trocar_octal, valor)


def _extrair_strings_pdf_array(conteudo_array, cmap):
    partes = []
    for token in re.finditer(r"<([0-9A-Fa-f\s]+)>|\(((?:\\.|[^\\)])*)\)", conteudo_array, re.S):
        if token.group(1):
            partes.append(_decode_hex_pdf(token.group(1), cmap))
        else:
            partes.append(_decode_literal_pdf(token.group(2)))
    return "".join(partes)


def _refs_pdf(texto):
    return [int(ref) for ref in re.findall(r"(\d+)\s+\d+\s+R", texto)]


def _objeto_catalogo_pdf(data):
    for match in re.finditer(rb"\b(\d+)\s+0\s+obj(.*?)endobj", data, re.S):
        corpo = match.group(2)
        if re.search(rb"/Type\s*/Catalog\b", corpo):
            return int(match.group(1)), corpo
    return None, b""


def _coletar_paginas_pdf(data, numero_objeto, visitados=None):
    visitados = visitados or set()
    if numero_objeto in visitados:
        return []
    visitados.add(numero_objeto)

    corpo = _obj_pdf(data, numero_objeto).decode("latin1", errors="ignore")
    if not corpo:
        return []

    if re.search(r"/Type\s*/Pages\b", corpo) or "/Kids" in corpo:
        match_kids = re.search(r"/Kids\s*\[(.*?)\]", corpo, re.S)
        if not match_kids:
            return []
        paginas = []
        for filho in _refs_pdf(match_kids.group(1)):
            paginas.extend(_coletar_paginas_pdf(data, filho, visitados))
        return paginas

    if re.search(r"/Type\s*/Page\b", corpo):
        return [numero_objeto]

    return []


def _fontes_pdf(data, corpo_pagina):
    fontes = {}
    for bloco_fontes in re.findall(r"/Font\s*<<(.*?)>>", corpo_pagina, re.S):
        for nome_fonte, numero_objeto in re.findall(r"/([A-Za-z0-9]+)\s+(\d+)\s+\d+\s+R", bloco_fontes):
            corpo_fonte = _obj_pdf(data, int(numero_objeto)).decode("latin1", errors="ignore")
            match_unicode = re.search(r"/ToUnicode\s+(\d+)\s+\d+\s+R", corpo_fonte)
            fontes[nome_fonte] = {}
            if match_unicode:
                fontes[nome_fonte] = _parse_cmap(
                    _stream_pdf(_obj_pdf(data, int(match_unicode.group(1))))
                )
    return fontes


def _conteudos_pagina_pdf(corpo_pagina):
    match_conteudo = re.search(r"/Contents\s+(?:\[(.*?)\]|(\d+)\s+\d+\s+R)", corpo_pagina, re.S)
    if not match_conteudo:
        return []
    if match_conteudo.group(1):
        return _refs_pdf(match_conteudo.group(1))
    return [int(match_conteudo.group(2))]


def _extrair_texto_stream_pdf(conteudo, fontes):
    partes = []
    fonte_atual = ""

    token_re = re.compile(
        r"/(?P<fonte>[A-Za-z0-9]+)\s+[0-9.]+\s+Tf|"
        r"(?P<tdx>-?\d+(?:\.\d+)?)\s+(?P<tdy>-?\d+(?:\.\d+)?)\s+T[dD]|"
        r"(?P<tm>(?:-?\d+(?:\.\d+)?\s+){5}-?\d+(?:\.\d+)?)\s+Tm|"
        r"<(?P<hex>[0-9A-Fa-f\s]+)>\s*Tj|"
        r"\(((?:\\.|[^\\)])*)\)\s*Tj|"
        r"\[(?P<array>.*?)\]\s*TJ|"
        r"(?P<linha>T\*)",
        re.S,
    )

    def adicionar_espaco():
        if partes and partes[-1] not in {" ", "\n"}:
            partes.append(" ")

    def adicionar_quebra():
        while partes and partes[-1] == " ":
            partes.pop()
        if partes and partes[-1] != "\n":
            partes.append("\n")

    for bloco in re.findall(r"BT(.*?)ET", conteudo, re.S):
        for token in token_re.finditer(bloco):
            if token.group("fonte"):
                fonte_atual = token.group("fonte")
                continue

            if token.group("tdx") is not None:
                dx = float(token.group("tdx"))
                dy = float(token.group("tdy"))
                if dy < -1:
                    adicionar_quebra()
                elif dx > 1:
                    adicionar_espaco()
                continue

            if token.group("tm") or token.group("linha"):
                adicionar_quebra()
                continue

            cmap = fontes.get(fonte_atual, {})
            if token.group("hex"):
                partes.append(_decode_hex_pdf(token.group("hex"), cmap))
            elif token.group(6):
                partes.append(_decode_literal_pdf(token.group(6)))
            elif token.group("array"):
                partes.append(_extrair_strings_pdf_array(token.group("array"), cmap))

        adicionar_quebra()

    texto = "".join(partes)
    linhas = [re.sub(r"[ \t]+", " ", linha).strip() for linha in texto.splitlines()]
    return "\n".join(linha for linha in linhas if linha)


def _extrair_texto_pdf(data):
    _catalogo_numero, catalogo = _objeto_catalogo_pdf(data)
    match_paginas = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalogo)
    if match_paginas:
        paginas = _coletar_paginas_pdf(data, int(match_paginas.group(1)))
    else:
        paginas_obj = _obj_pdf(data, 2).decode("latin1", errors="ignore")
        match_kids = re.search(r"/Kids\s*\[(.*?)\]", paginas_obj, re.S)
        paginas = [int(x) for x in re.findall(r"(\d+)\s+\d+\s+R", match_kids.group(1))] if match_kids else []

    if not paginas:
        return ""

    partes = []

    for pagina in paginas:
        corpo_pagina_bytes = _obj_pdf(data, pagina)
        corpo_pagina = corpo_pagina_bytes.decode("latin1", errors="ignore")
        fontes = _fontes_pdf(data, corpo_pagina)
        conteudos = _conteudos_pagina_pdf(corpo_pagina)

        for numero_conteudo in conteudos:
            conteudo = _stream_pdf(_obj_pdf(data, numero_conteudo)).decode("latin1", errors="ignore")
            texto_conteudo = _extrair_texto_stream_pdf(conteudo, fontes)
            if texto_conteudo:
                partes.append(texto_conteudo)

    return "\n".join(partes)


def extrair_texto_normativo(nome_arquivo, conteudo):
    nome = nome_arquivo.lower()
    if nome.endswith(".pdf"):
        texto = _extrair_texto_pdf(conteudo)
        if texto.strip():
            return texto
        return ""
    for encoding in ["utf-8", "latin1"]:
        try:
            return conteudo.decode(encoding, errors="ignore")
        except Exception:
            pass
    return ""


def inferir_perfil_decreto(nome_arquivo, texto):
    texto_norm = texto.lower()

    minimo_precos = 3
    match_minimo = re.search(r"(?:mínimo|minimo|conjunto de)\s*(?:de\s*)?(\d+)\s*(?:preços|precos|fornecedores)", texto_norm)
    if match_minimo:
        minimo_precos = int(match_minimo.group(1))

    prazo_dias = 183
    match_meses = re.search(r"(\d+)\s*\(\s*\w+\s*\)\s*meses|(\d+)\s*meses", texto_norm)
    if match_meses:
        meses = int(match_meses.group(1) or match_meses.group(2))
        prazo_dias = meses * 30 if meses != 6 else 183
    elif re.search(r"1\s*\(\s*um\s*\)\s*ano|1\s*ano|um ano", texto_norm):
        prazo_dias = 365

    bases = []
    decreto = re.search(r"decreto\s+n[ºo°]?\s*([\d./-]+)", texto_norm, re.I)
    if decreto:
        bases.append(f"Decreto enviado nº {decreto.group(1)}")
    else:
        bases.append(f"Decreto enviado: {nome_arquivo}")

    if "14.133" in texto_norm or "14133" in texto_norm:
        bases.append("Lei Federal nº 14.133/2021")

    codigo_base = re.sub(r"[^a-z0-9]+", "_", nome_arquivo.lower()).strip("_")[:40]
    return PerfilNormativo(
        codigo=f"upload_{codigo_base}",
        nome=f"Perfil por decreto enviado - {nome_arquivo[:45]}",
        base_legal=tuple(dict.fromkeys(bases)),
        prazo_precos_dias=prazo_dias,
        minimo_precos=minimo_precos,
        permite_menos_tres_com_justificativa=True,
        observacoes=(
            "Perfil criado automaticamente a partir do decreto enviado. "
            "Revise os parametros antes de anexar o dossie ao processo."
        ),
    )


def _parse_data(valor):
    if valor is None:
        return None

    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return None

    formatos = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]

    for formato in formatos:
        try:
            return datetime.strptime(texto[:19], formato).date()
        except ValueError:
            pass

    return None


def _obter_valor(resultado):
    return converter_numero(
        resultado.get("valor_unitario")
        if isinstance(resultado, dict)
        else None
    )


def _obter_data(resultado):
    if not isinstance(resultado, dict):
        return None

    return (
        _parse_data(resultado.get("data_referencia"))
        or _parse_data(resultado.get("data_homologacao"))
        or _parse_data(resultado.get("data"))
    )


def _obter_origem(resultado):
    if not isinstance(resultado, dict):
        return ""
    return (
        resultado.get("origem")
        or resultado.get("fonte_base")
        or resultado.get("modo_busca")
        or ""
    )


def _percentil_ordenado(valores, proporcao):
    if not valores:
        return None

    posicao = (len(valores) - 1) * proporcao
    inferior = int(posicao)
    superior = min(inferior + 1, len(valores) - 1)
    peso = posicao - inferior
    return valores[inferior] * (1 - peso) + valores[superior] * peso


def _classificar_precos(valores):
    if len(valores) < 4:
        return valores, []

    ordenados = sorted(valores)
    q1 = _percentil_ordenado(ordenados, 0.25)
    q3 = _percentil_ordenado(ordenados, 0.75)
    intervalo = q3 - q1

    if intervalo <= 0:
        return valores, []

    limite_inferior = q1 - 1.5 * intervalo
    limite_superior = q3 + 1.5 * intervalo

    aproveitados = [
        valor for valor in valores
        if limite_inferior <= valor <= limite_superior
    ]
    descartados = [
        valor for valor in valores
        if valor < limite_inferior or valor > limite_superior
    ]

    return aproveitados, descartados


def avaliar_conformidade_pesquisa(
    resultados,
    data_pesquisa=None,
    descricao_objeto="",
    responsavel="",
    justificativa_menos_tres="",
    justificativa_descartes="",
    metodo_preferido="auto",
    perfil_codigo="joia_rs_5337",
):
    perfil = obter_perfil_normativo(perfil_codigo)

    if data_pesquisa is None:
        data_pesquisa = date.today()

    precos = []
    precos_no_prazo = []
    fontes_consultadas = set()
    linhas_validas = []

    for resultado in resultados:
        valor = _obter_valor(resultado)
        if valor is None or valor <= 0:
            continue

        precos.append(valor)
        fontes_consultadas.add(_obter_origem(resultado) or "Nao informada")
        linhas_validas.append(resultado)

        data_referencia = _obter_data(resultado)
        if data_referencia is not None:
            dias = (data_pesquisa - data_referencia).days
            if 0 <= dias <= perfil.prazo_precos_dias:
                precos_no_prazo.append(valor)

    precos_aproveitados, precos_descartados = _classificar_precos(precos)

    estatisticas = {
        "perfil_normativo": perfil.nome,
        "perfil_codigo": perfil.codigo,
        "base_legal": list(perfil.base_legal),
        "prazo_precos_dias": perfil.prazo_precos_dias,
        "minimo_precos": perfil.minimo_precos,
        "total_precos": len(precos),
        "precos_no_prazo_6_meses": len(precos_no_prazo),
        "precos_no_prazo": len(precos_no_prazo),
        "precos_aproveitados": len(precos_aproveitados),
        "precos_descartados": len(precos_descartados),
        "media": None,
        "mediana": None,
        "menor": None,
        "maior": None,
        "metodo_sugerido": "",
        "valor_sugerido": None,
        "alertas": [],
        "fontes_consultadas": sorted(fontes_consultadas),
        "checklist": [],
        "precos_lista": precos,
        "precos_aproveitados_lista": precos_aproveitados,
        "precos_descartados_lista": precos_descartados,
        "justificativas_exigidas": [],
    }

    if precos_aproveitados:
        estatisticas["media"] = mean(precos_aproveitados)
        estatisticas["mediana"] = median(precos_aproveitados)
        estatisticas["menor"] = min(precos_aproveitados)
        estatisticas["maior"] = max(precos_aproveitados)

        if len(precos_aproveitados) >= perfil.minimo_precos:
            amplitude = estatisticas["maior"] - estatisticas["menor"]
            variacao_relativa = amplitude / estatisticas["mediana"] if estatisticas["mediana"] else 0

            if metodo_preferido == "media":
                estatisticas["metodo_sugerido"] = "media"
                estatisticas["valor_sugerido"] = estatisticas["media"]
            elif metodo_preferido == "mediana":
                estatisticas["metodo_sugerido"] = "mediana"
                estatisticas["valor_sugerido"] = estatisticas["mediana"]
            elif metodo_preferido == "menor":
                estatisticas["metodo_sugerido"] = "menor preco"
                estatisticas["valor_sugerido"] = estatisticas["menor"]
            elif variacao_relativa > 0.25:
                estatisticas["metodo_sugerido"] = "mediana"
                estatisticas["valor_sugerido"] = estatisticas["mediana"]
                estatisticas["alertas"].append(
                    "Ha grande variacao entre os valores; a mediana foi sugerida para reduzir distorcao."
                )
            else:
                estatisticas["metodo_sugerido"] = "media"
                estatisticas["valor_sugerido"] = estatisticas["media"]
        else:
            estatisticas["metodo_sugerido"] = "menor preco disponivel, com justificativa"
            estatisticas["valor_sugerido"] = estatisticas["menor"]

    if len(precos) < perfil.minimo_precos:
        estatisticas["alertas"].append(
            f"O perfil normativo exige calculo sobre {perfil.minimo_precos} ou mais precos; usar menos exige justificativa no processo."
        )
        if perfil.permite_menos_tres_com_justificativa and not justificativa_menos_tres.strip():
            estatisticas["justificativas_exigidas"].append(
                f"Justificar uso de menos de {perfil.minimo_precos} precos."
            )

    if len(precos_no_prazo) < perfil.minimo_precos:
        estatisticas["alertas"].append(
            f"Ha menos de {perfil.minimo_precos} precos dentro do prazo de {perfil.prazo_precos_dias} dias do perfil normativo."
        )

    if precos_descartados:
        estatisticas["alertas"].append(
            "Foram identificados valores fora da faixa estatistica; a desconsideracao precisa ser justificada."
        )
        if not justificativa_descartes.strip():
            estatisticas["justificativas_exigidas"].append(
                "Justificar descarte de valores inexequiveis, inconsistentes ou excessivamente elevados."
            )

    checklist = [
        ("Perfil normativo definido", bool(perfil.codigo)),
        ("Descricao do objeto", bool(str(descricao_objeto).strip())),
        ("Responsavel pela pesquisa", bool(str(responsavel).strip())),
        ("Fontes consultadas caracterizadas", bool(fontes_consultadas)),
        ("Serie de precos coletados", len(precos) > 0),
        ("Metodo estatistico definido", bool(estatisticas["metodo_sugerido"])),
        ("Memoria de calculo gerada", len(precos) > 0),
        ("Documentos/evidencias informados", any(
            str(r.get("evidencia", "") or r.get("link", "") or r.get("link_licitacon", "")).strip()
            for r in linhas_validas
            if isinstance(r, dict)
        )),
    ]

    estatisticas["checklist"] = [
        {"item": item, "ok": ok}
        for item, ok in checklist
    ]

    return estatisticas


def formatar_moeda(valor):
    if valor is None:
        return "-"

    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
