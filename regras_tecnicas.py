import re
from util import normalizar


# =========================
# MEDIDAS / BITOLAS
# =========================

def extrair_bitolas_mm(texto):
    """
    Extrai medidas em mm, especialmente bitolas tipo:
    2,5 mm
    2.5mm
    2,50mm
    1x1,5mm
    3 x 2,5 mm
    """

    texto_original = str(texto).lower()

    padroes = [
        r"(\d+(?:[,.]\d+)?)\s*mm\b",
        r"\b\d+\s*x\s*(\d+(?:[,.]\d+)?)\s*mm\b",
        r"\b\d+x(\d+(?:[,.]\d+)?)mm\b",
    ]

    medidas = []

    for padrao in padroes:
        encontrados = re.findall(padrao, texto_original, flags=re.IGNORECASE)

        for valor in encontrados:
            try:
                valor_float = float(str(valor).replace(",", "."))
                medidas.append(valor_float)
            except:
                pass

    return sorted(list(set(medidas)))


def extrair_voltagens(texto):
    """
    Extrai voltagens tipo:
    220V
    380 V
    220 volts
    24/24V
    110/220 V
    """

    texto_original = str(texto).lower()

    encontrados = []

    for grupo in re.findall(
        r"\b(\d{2,4}(?:\s*/\s*\d{2,4})*)\s*(?:v|volt|volts)\b",
        texto_original,
        flags=re.IGNORECASE
    ):
        encontrados.extend(re.findall(r"\d{2,4}", grupo))

    voltagens = []

    for valor in encontrados:
        try:
            voltagens.append(int(valor))
        except:
            pass

    return sorted(list(set(voltagens)))


def extrair_potencias_w(texto):
    texto_original = str(texto).lower()
    encontrados = re.findall(r"\b(\d+(?:[,.]\d+)?)\s*w\b", texto_original, flags=re.IGNORECASE)

    potencias = []

    for valor in encontrados:
        try:
            potencias.append(float(str(valor).replace(",", ".")))
        except:
            pass

    return sorted(list(set(potencias)))


def extrair_capacitancias(texto):
    texto_original = str(texto).lower()
    capacitancias = []

    padrao = r"\b(\d+(?:[,.]\d+)?(?:\s*/\s*\d+(?:[,.]\d+)?)*)\s*(uf|u f|µf|mf|micro|micros|microfarad|microfarads)\b"

    for grupo, unidade in re.findall(padrao, texto_original, flags=re.IGNORECASE):
        unidade_norm = unidade.replace(" ", "")

        if unidade_norm in {"µf", "micro", "micros", "microfarad", "microfarads"}:
            unidade_norm = "uf"

        for valor in re.findall(r"\d+(?:[,.]\d+)?", grupo):
            try:
                capacitancias.append((float(str(valor).replace(",", ".")), unidade_norm))
            except:
                pass

    return sorted(list(set(capacitancias)))


# =========================
# CORRENTE / AMPERAGEM
# =========================

def _numero_para_float(valor):
    try:
        return float(str(valor).replace(",", ".").strip())
    except:
        return None


def extrair_correntes_a(texto):
    """
    Extrai correntes em ampères.

    Exemplos aceitos:
    - 5,5 - 8 A
    - 5,5 a 8A
    - 5.5 até 8 A
    - 10A
    - 10 A
    - faixa 10A a 15A
    - 0,63-1A
    """

    texto_original = str(texto).lower()
    texto_original = texto_original.replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
    texto_original = texto_original.replace("é", "e").replace("ê", "e")
    texto_original = texto_original.replace("í", "i")
    texto_original = texto_original.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    texto_original = texto_original.replace("ú", "u")
    texto_original = texto_original.replace("–", "-").replace("—", "-")

    correntes = []

    padrao_faixa_final = (
        r"\b(\d+(?:[,.]\d+)?)\s*"
        r"(?:-|a|ate|até)\s*"
        r"(\d+(?:[,.]\d+)?)\s*a\b"
    )

    for ini, fim in re.findall(padrao_faixa_final, texto_original, flags=re.IGNORECASE):
        v_ini = _numero_para_float(ini)
        v_fim = _numero_para_float(fim)

        if v_ini is not None and v_fim is not None:
            menor = min(v_ini, v_fim)
            maior = max(v_ini, v_fim)
            correntes.append({"min": menor, "max": maior, "tipo": "faixa"})

    padrao_faixa_duplo_a = (
        r"\b(\d+(?:[,.]\d+)?)\s*a\s*"
        r"(?:-|a|ate|até)\s*"
        r"(\d+(?:[,.]\d+)?)\s*a\b"
    )

    for ini, fim in re.findall(padrao_faixa_duplo_a, texto_original, flags=re.IGNORECASE):
        v_ini = _numero_para_float(ini)
        v_fim = _numero_para_float(fim)

        if v_ini is not None and v_fim is not None:
            menor = min(v_ini, v_fim)
            maior = max(v_ini, v_fim)
            correntes.append({"min": menor, "max": maior, "tipo": "faixa"})

    texto_sem_faixas = re.sub(padrao_faixa_final, " ", texto_original, flags=re.IGNORECASE)
    texto_sem_faixas = re.sub(padrao_faixa_duplo_a, " ", texto_sem_faixas, flags=re.IGNORECASE)

    for valor in re.findall(r"\b(\d+(?:[,.]\d+)?)\s*a\b", texto_sem_faixas, flags=re.IGNORECASE):
        v = _numero_para_float(valor)
        if v is not None:
            correntes.append({"min": v, "max": v, "tipo": "pontual"})

    unicos = []
    chaves = set()

    for c in correntes:
        chave = (round(c["min"], 4), round(c["max"], 4), c["tipo"])
        if chave not in chaves:
            chaves.add(chave)
            unicos.append(c)

    return unicos


def correntes_compativeis(correntes_busca, correntes_resultado):
    """
    Compara faixas de corrente.

    Regra:
    - Se busca 5,5-8A e resultado 10-15A: incompatível.
    - Se houver sobreposição entre as faixas: compatível.
    """

    if not correntes_busca or not correntes_resultado:
        return True

    for cb in correntes_busca:
        for cr in correntes_resultado:
            busca_min = cb["min"]
            busca_max = cb["max"]
            res_min = cr["min"]
            res_max = cr["max"]

            existe_sobreposicao = busca_min <= res_max and res_min <= busca_max

            if existe_sobreposicao:
                return True

    return False


def formatar_correntes(correntes):
    partes = []

    for c in correntes:
        if c["min"] == c["max"]:
            partes.append(f"{c['min']:g}A")
        else:
            partes.append(f"{c['min']:g}-{c['max']:g}A")

    return ", ".join(partes)


# =========================
# UNIDADES
# =========================

def normalizar_unidade(unidade):
    u = normalizar(unidade)

    equivalencias = {
        "un": "unidade",
        "und": "unidade",
        "unid": "unidade",
        "unidade": "unidade",
        "unidades": "unidade",

        "m": "metro",
        "mt": "metro",
        "mts": "metro",
        "metro": "metro",
        "metros": "metro",

        "l": "litro",
        "lt": "litro",
        "lts": "litro",
        "litro": "litro",
        "litros": "litro",

        "kg": "kg",
        "quilo": "kg",
        "quilos": "kg",
        "kilograma": "kg",
        "kilogramas": "kg",

        "g": "grama",
        "gr": "grama",
        "grama": "grama",
        "gramas": "grama",

        "rolo": "rolo",
        "rolos": "rolo",

        "par": "par",
        "pares": "par",

        "cx": "caixa",
        "caixa": "caixa",
        "caixas": "caixa",

        "pct": "pacote",
        "pacote": "pacote",
        "pacotes": "pacote",
    }

    return equivalencias.get(u, u)


def unidades_compativeis(unidade_busca, unidade_resultado):
    if not unidade_busca or not unidade_resultado:
        return True

    ub = normalizar_unidade(unidade_busca)
    ur = normalizar_unidade(unidade_resultado)

    if not ub or not ur:
        return True

    return ub == ur


# =========================
# PRODUTO PRINCIPAL
# =========================

def inicio_descricao(texto, qtd_palavras=10):
    texto_norm = normalizar(texto)
    return " ".join(texto_norm.split()[:qtd_palavras])


def resultado_parece_componente_acessorio(descricao_resultado, termo_principal):
    """
    Evita aceitar item em que o termo buscado aparece apenas como componente interno
    de outro produto.

    Exemplo:
    Busca: relé térmico 5,5-8A
    Resultado: COMPRESSOR DE AR ... relé térmico protetor ...
    -> Deve ser eliminado, pois o item principal é compressor, não relé.
    """

    resultado_norm = normalizar(descricao_resultado)
    inicio = inicio_descricao(descricao_resultado, 10)

    produtos_principais_incompativeis = {
        "compressor", "motor", "bomba", "maquina", "equipamento",
        "aparelho", "cadeira", "veiculo", "trator", "rolo", "kit",
        "painel", "quadro", "sistema", "conjunto"
    }

    if termo_principal not in resultado_norm:
        return False

    palavras_inicio = set(inicio.split())

    if termo_principal not in palavras_inicio:
        if palavras_inicio.intersection(produtos_principais_incompativeis):
            return True

    marcadores_componente = [
        "possui", "inclui", "contendo", "composto",
        "dispositivo", "protetor", "interno", "integrado"
    ]

    pos_termo = resultado_norm.find(termo_principal)

    if pos_termo > 40:
        trecho_antes = resultado_norm[:pos_termo]
        if any(m in trecho_antes for m in marcadores_componente):
            return True

    return False


# =========================
# REGRAS TÉCNICAS
# =========================

def validar_regras_tecnicas(descricao_busca, descricao_resultado, unidade_busca=None, unidade_resultado=None):
    """
    Regra geral:
    - divergência técnica clara elimina;
    - ausência de detalhe técnico relevante apenas alerta/penaliza pouco;
    - componente acessório dentro de outro equipamento elimina.
    """

    avisos = []
    penalidade = 0
    ok = True

    busca_norm = normalizar(descricao_busca)
    resultado_norm = normalizar(descricao_resultado)

    # =========================
    # BITOLA MM
    # =========================

    bitolas_busca = extrair_bitolas_mm(descricao_busca)
    bitolas_resultado = extrair_bitolas_mm(descricao_resultado)

    if bitolas_busca:
        if not bitolas_resultado:
            penalidade += 15
            avisos.append(
                f"Busca informa bitola {bitolas_busca}, mas o resultado não apresenta bitola em mm."
            )
        else:
            encontrou_compatibilidade = any(
                abs(b - r) <= 0.01
                for b in bitolas_busca
                for r in bitolas_resultado
            )

            if not encontrou_compatibilidade:
                ok = False
                penalidade += 60
                avisos.append(
                    f"Divergência de bitola: busca {bitolas_busca} mm, resultado {bitolas_resultado} mm."
                )

    # =========================
    # VOLTAGEM
    # =========================

    voltagens_busca = extrair_voltagens(descricao_busca)
    voltagens_resultado = extrair_voltagens(descricao_resultado)

    if voltagens_busca:
        if voltagens_resultado:
            encontrou_voltagem = any(v in voltagens_resultado for v in voltagens_busca)

            if not encontrou_voltagem:
                penalidade += 35
                avisos.append(
                    f"Divergência de voltagem: busca {voltagens_busca}V, resultado {voltagens_resultado}V."
                )

    # =========================
    # POTENCIA W
    # =========================

    potencias_busca = extrair_potencias_w(descricao_busca)
    potencias_resultado = extrair_potencias_w(descricao_resultado)

    if potencias_busca and potencias_resultado:
        encontrou_potencia = any(
            abs(pb - pr) <= 0.01
            for pb in potencias_busca
            for pr in potencias_resultado
        )

        if not encontrou_potencia:
            ok = False
            penalidade += 70
            avisos.append(
                f"Divergencia de potencia: busca {potencias_busca}W, resultado {potencias_resultado}W."
            )

    # =========================
    # CAPACITANCIA UF/MF
    # =========================

    capacitancias_busca = extrair_capacitancias(descricao_busca)
    capacitancias_resultado = extrair_capacitancias(descricao_resultado)

    if capacitancias_busca and capacitancias_resultado:
        encontrou_capacitancia = any(
            abs(cb[0] - cr[0]) <= 0.01 and cb[1] == cr[1]
            for cb in capacitancias_busca
            for cr in capacitancias_resultado
        )

        if not encontrou_capacitancia:
            ok = False
            penalidade += 80
            avisos.append(
                f"Divergencia de capacitancia: busca {capacitancias_busca}, resultado {capacitancias_resultado}."
            )

    # =========================
    # CORRENTE / AMPERAGEM
    # =========================

    correntes_busca = extrair_correntes_a(descricao_busca)
    correntes_resultado = extrair_correntes_a(descricao_resultado)

    item_eletrico_com_corrente = any(t in busca_norm for t in [
        "rele", "disjuntor", "contator", "contatora",
        "fusivel", "chave", "interruptor", "termico", "sobrecarga"
    ])

    if correntes_busca:
        if correntes_resultado:
            if not correntes_compativeis(correntes_busca, correntes_resultado):
                ok = False
                penalidade += 80
                avisos.append(
                    "Divergência de corrente/amperagem: "
                    f"busca {formatar_correntes(correntes_busca)}, "
                    f"resultado {formatar_correntes(correntes_resultado)}."
                )
        else:
            if item_eletrico_com_corrente:
                penalidade += 8
                avisos.append(
                    "Busca informa corrente/amperagem, mas o resultado não apresenta faixa ou valor de corrente. Conferir manualmente."
                )

    # =========================
    # UNIDADE
    # =========================

    if unidade_busca and unidade_resultado:
        if not unidades_compativeis(unidade_busca, unidade_resultado):
            penalidade += 25
            avisos.append(
                f"Unidade possivelmente incompatível: busca '{unidade_busca}', resultado '{unidade_resultado}'."
            )

    # =========================
    # REGRAS ESPECÍFICAS POR TIPO
    # =========================

    busca_analogica = (
        "analogico" in busca_norm
        or "analogica" in busca_norm
        or "anal gico" in busca_norm
        or "anal gica" in busca_norm
    )
    busca_digital = "digital" in busca_norm
    resultado_analogico = "analogico" in resultado_norm or "analogica" in resultado_norm
    resultado_digital = "digital" in resultado_norm

    if busca_analogica and resultado_digital and not resultado_analogico:
        ok = False
        penalidade += 70
        avisos.append("Busca informa item analogico, mas o resultado aparenta ser digital.")

    if busca_digital and resultado_analogico and not resultado_digital:
        ok = False
        penalidade += 70
        avisos.append("Busca informa item digital, mas o resultado aparenta ser analogico.")

    if any(t in busca_norm for t in ["fio", "cabo", "condutor"]):
        if bitolas_busca and bitolas_resultado:
            encontrou = any(
                abs(b - r) <= 0.01
                for b in bitolas_busca
                for r in bitolas_resultado
            )

            if not encontrou:
                ok = False
                avisos.append("Item de fio/cabo com bitola diferente da pesquisada.")

    if "rele" in busca_norm and "falta" in busca_norm and "fase" in busca_norm:
        if not ("falta" in resultado_norm and "fase" in resultado_norm):
            ok = False
            penalidade += 60
            avisos.append("Busca é relé falta de fase, mas o resultado não contém falta de fase.")

        if resultado_parece_componente_acessorio(descricao_resultado, "rele"):
            ok = False
            penalidade += 80
            avisos.append("O resultado aparenta citar relé apenas como componente de outro equipamento.")

    if "rele" in busca_norm and ("termico" in busca_norm or "termica" in busca_norm) and "sobrecarga" in busca_norm:
        if "rele" not in resultado_norm:
            ok = False
            penalidade += 60
            avisos.append("Busca é relé térmico de sobrecarga, mas o resultado não contém relé.")

        if not ("termico" in resultado_norm or "termica" in resultado_norm):
            penalidade += 12
            avisos.append("Busca é relé térmico de sobrecarga, mas o resultado não contém expressamente térmico/térmica.")

        if resultado_parece_componente_acessorio(descricao_resultado, "rele"):
            ok = False
            penalidade += 80
            avisos.append("O resultado aparenta citar relé apenas como componente de outro equipamento, não como item principal.")

        if "sobrecarga" not in resultado_norm:
            penalidade += 8
            avisos.append("Busca informa sobrecarga, mas o resultado não contém esse termo.")

    return {
        "ok": ok,
        "penalidade": penalidade,
        "avisos": avisos,
        "bitolas_busca": bitolas_busca,
        "bitolas_resultado": bitolas_resultado,
        "voltagens_busca": voltagens_busca,
        "voltagens_resultado": voltagens_resultado,
        "correntes_busca": correntes_busca,
        "correntes_resultado": correntes_resultado
    }
