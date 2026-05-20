import json
import logging
import os
import re
import time
from copy import deepcopy

from openai import OpenAI

from config.app_settings import MODELO_IA, PALAVRAS_FRACAS
from config.runtime_settings import DEBUG_IA, OPENAI_DISABLE_MINUTES
from ia.ia_cache import obter_cache_ia, salvar_cache_ia
from utils.util import normalizar
from search.intelligence import enriquecer_criterios_contextuais


logger = logging.getLogger("ia")
_OPENAI_DESABILITADO_ATE = 0
_CRITERIOS_MEM_CACHE = {}


def _tokens_aproximados(texto):
    return max(1, int(len(texto or "") / 4))


def openai_temporariamente_desativada():
    return time.time() < _OPENAI_DESABILITADO_ATE


def status_openai_local():
    if not os.getenv("OPENAI_API_KEY"):
        return "sem_chave"
    if openai_temporariamente_desativada():
        return "quota_exceeded"
    return "ok"


def _desativar_openai_temporariamente(motivo):
    global _OPENAI_DESABILITADO_ATE
    minutos = max(1, OPENAI_DISABLE_MINUTES)
    _OPENAI_DESABILITADO_ATE = time.time() + (minutos * 60)
    logger.warning(
        "OPENAI temporariamente desativada por quota/rate limit motivo=%s minutos=%s",
        motivo,
        minutos,
    )


def gerar_descricao_sugerida_local(descricao):
    texto = normalizar(descricao)
    palavras = texto.split()
    ruido_descritivo = {
        "confeccionado", "confeccionada", "fabricado", "fabricada",
        "tamanho", "tam", "tipo", "modelo", "com", "para", "uso",
    }
    manter = []

    for p in palavras:
        if p in ruido_descritivo:
            continue
        if p in {"rele", "rele", "fase", "fases", "falta", "neutro", "trifasica", "trifasico"}:
            manter.append(p)
        elif re.match(r"^\d+v$", p):
            manter.append(p)
        elif len(p) >= 4 and p not in PALAVRAS_FRACAS:
            manter.append(p)

    manter = list(dict.fromkeys(manter))

    extras_criticos = []
    for match in re.finditer(r"\b(?:n|no|num|numero|nº)\s*\.?\s*(\d+[a-z]?)\b", texto):
        extras_criticos.extend(["n", match.group(1)])
    for match in re.finditer(r"\b\d+(?:[,.]\d+)?\s*(?:mm|cm|m|pol|awg)\b", texto):
        extras_criticos.append(match.group(0).replace(" ", ""))
    if "pincel" in palavras and "pelo" in palavras and "boi" in palavras:
        for termo in ["pincel", "chato", "pelo", "boi"]:
            if termo in palavras and termo not in manter:
                manter.append(termo)
    for termo in extras_criticos:
        termo = normalizar(termo)
        if termo and termo not in manter:
            manter.append(termo)

    if "rele" in manter and "falta" in manter and "fase" in manter:
        base = ["rele", "falta", "fase"]
        if "380v" in manter:
            base.append("380v")
        elif "220v" in manter:
            base.append("220v")
        return " ".join(base)

    if len(manter) >= 2:
        return " ".join(manter[:7])

    return descricao


def extrair_criterios_simples(descricao):
    texto = normalizar(descricao)
    palavras = texto.split()
    termos = []

    for p in palavras:
        if p in {"confeccionado", "confeccionada", "fabricado", "fabricada", "tamanho", "tam", "tipo", "modelo"}:
            continue
        if len(p) >= 4 and p not in PALAVRAS_FRACAS:
            termos.append(p)

    termos = list(dict.fromkeys(termos))
    for termo in re.findall(r"\b(?:n|no|num|numero|nº)\s*\.?\s*(\d+[a-z]?)\b", texto):
        termos.append(f"n {termo}")
    if "pincel" in palavras and "pelo" in palavras and "boi" in palavras:
        termos.append("pelo boi")
        termos.append("n 0" if "0" in palavras else "")
    termos = [termo for termo in list(dict.fromkeys(termos)) if termo]
    frase_principal = " ".join(termos[:2]) if len(termos) >= 2 else " ".join(termos[:1])
    descricao_sugerida = gerar_descricao_sugerida_local(descricao)

    obrigatorios = []
    if frase_principal:
        obrigatorios.append(frase_principal)
    obrigatorios += termos[:4]

    criterios = {
        "termos_obrigatorios": list(dict.fromkeys(obrigatorios))[:8],
        "termos_importantes": termos[4:20],
        "termos_excluir": [],
        "termos_proibidos": [],
        "frases_chave": [frase_principal] if frase_principal else [],
        "descricao_resumida": descricao,
        "descricao_sugerida_licitacon": descricao_sugerida,
    }
    return enriquecer_criterios_contextuais(descricao, criterios)


def _validar_descricao_sugerida(descricao, descricao_sugerida):
    descricao_sugerida_norm = normalizar(descricao_sugerida)
    if (
        not descricao_sugerida
        or len(descricao_sugerida_norm.split()) < 2
        or descricao_sugerida_norm in {"rele", "rele falta", "bloco", "sensor", "chave"}
    ):
        return gerar_descricao_sugerida_local(descricao)

    texto_original_norm = normalizar(descricao)
    if "rele" in texto_original_norm and "falta" in texto_original_norm and "fase" in texto_original_norm:
        return gerar_descricao_sugerida_local(descricao)

    return descricao_sugerida


def extrair_criterios_com_ia(descricao):
    inicio_total = time.perf_counter()
    chave_memoria = normalizar(descricao)
    if chave_memoria in _CRITERIOS_MEM_CACHE:
        logger.debug("IA memoria_cache_hit descricao=%r", descricao)
        return deepcopy(_CRITERIOS_MEM_CACHE[chave_memoria])

    try:
        cached = obter_cache_ia(descricao)
    except Exception as erro:
        cached = None
        logger.warning("IA cache indisponivel descricao=%r erro=%s", descricao, erro)

    if cached is not None:
        logger.debug(
            "IA cache_hit descricao=%r modelo=%s tempo_ms=%s tokens_aprox=%s custo_estimado=%s",
            descricao,
            MODELO_IA,
            round((time.perf_counter() - inicio_total) * 1000, 2),
            _tokens_aproximados(descricao),
            0,
        )
        resultado_cache = enriquecer_criterios_contextuais(descricao, cached)
        _CRITERIOS_MEM_CACHE[chave_memoria] = deepcopy(resultado_cache)
        return deepcopy(resultado_cache)

    logger.debug("IA cache_miss descricao=%r modelo=%s", descricao, MODELO_IA)

    if openai_temporariamente_desativada():
        logger.debug("IA fallback_local descricao=%r motivo=openai_desativada", descricao)
        resultado_local = extrair_criterios_simples(descricao)
        _CRITERIOS_MEM_CACHE[chave_memoria] = deepcopy(resultado_local)
        return deepcopy(resultado_local)

    chave = os.getenv("OPENAI_API_KEY")
    if not chave:
        logger.debug("IA fallback_local descricao=%r motivo=sem_openai_api_key", descricao)
        resultado_local = extrair_criterios_simples(descricao)
        _CRITERIOS_MEM_CACHE[chave_memoria] = deepcopy(resultado_local)
        return deepcopy(resultado_local)

    client = OpenAI(api_key=chave)
    prompt = f"""
Voce e um assistente tecnico especialista em compras publicas e pesquisa de precos no LicitaCon/TCE-RS.

Analise a descricao abaixo e retorne SOMENTE um JSON valido:

Descricao:
{descricao}

Formato obrigatorio:

{{
  "categoria": "",
  "nucleo_tecnico": "",
  "medidas": [],
  "materiais": [],
  "unidade": "",
  "aplicacoes": [],
  "termos_obrigatorios": [],
  "termos_importantes": [],
  "termos_excluir": [],
  "termos_proibidos": [],
  "frases_chave": [],
  "quantidade_desejada": "",
  "descricao_resumida": "",
  "descricao_sugerida_licitacon": ""
}}

Regras:
- descricao_sugerida_licitacon deve ter de 2 a 5 palavras.
- Deve preservar o nucleo tecnico especifico.
- Evite termo generico sozinho.
- Exemplo ruim: "rele".
- Exemplo ruim: "rele falta".
- Exemplo bom: "rele falta fase".
- Exemplo bom: "rele falta fase 380v".
- Exemplo bom: "rele fotoeletrico".
- Exemplo bom: "bloco temporizador".
- Nao invente especificacoes.
- Normalize sem acento.
- Retorne apenas JSON.
"""

    try:
        inicio_ia = time.perf_counter()
        resposta = client.chat.completions.create(
            model=MODELO_IA,
            messages=[
                {
                    "role": "system",
                    "content": "Voce extrai criterios tecnicos para busca de precos publicos.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
        )

        conteudo = resposta.choices[0].message.content.strip()
        conteudo = conteudo.replace("```json", "").replace("```", "").strip()
        dados = json.loads(conteudo)
        descricao_sugerida = _validar_descricao_sugerida(
            descricao,
            dados.get("descricao_sugerida_licitacon", "").strip(),
        )
        resultado = {
            "categoria": dados.get("categoria", ""),
            "nucleo_tecnico": dados.get("nucleo_tecnico", ""),
            "medidas": dados.get("medidas", []),
            "materiais": dados.get("materiais", []),
            "unidade": dados.get("unidade", ""),
            "aplicacoes": dados.get("aplicacoes", []),
            "termos_obrigatorios": dados.get("termos_obrigatorios", []),
            "termos_importantes": dados.get("termos_importantes", []),
            "termos_excluir": dados.get("termos_excluir", []),
            "termos_proibidos": dados.get("termos_proibidos", []),
            "frases_chave": dados.get("frases_chave", []),
            "quantidade_desejada": dados.get("quantidade_desejada", ""),
            "descricao_resumida": dados.get("descricao_resumida", descricao),
            "descricao_sugerida_licitacon": descricao_sugerida,
        }
        resultado = enriquecer_criterios_contextuais(descricao, resultado)

        try:
            salvar_cache_ia(descricao, resultado)
        except Exception as erro:
            logger.warning("Falha ao gravar cache IA descricao=%r erro=%s", descricao, erro)

        logger.debug(
            "IA chamada_ok descricao=%r modelo=%s tempo_ia_ms=%s tempo_total_ms=%s tokens_aprox=%s custo_estimado=%s",
            descricao,
            MODELO_IA,
            round((time.perf_counter() - inicio_ia) * 1000, 2),
            round((time.perf_counter() - inicio_total) * 1000, 2),
            _tokens_aproximados(prompt),
            0,
        )
        if DEBUG_IA:
            logger.debug("IA resultado descricao=%r resultado=%s", descricao, resultado)
        _CRITERIOS_MEM_CACHE[chave_memoria] = deepcopy(resultado)
        return deepcopy(resultado)

    except Exception as erro:
        mensagem = str(erro).lower()
        if any(sinal in mensagem for sinal in ["429", "rate", "quota", "timeout", "timed out"]):
            _desativar_openai_temporariamente(str(erro))
        logger.warning(
            "IA fallback_local descricao=%r modelo=%s erro=%s tempo_total_ms=%s",
            descricao,
            MODELO_IA,
            erro,
            round((time.perf_counter() - inicio_total) * 1000, 2),
        )
        resultado_local = extrair_criterios_simples(descricao)
        _CRITERIOS_MEM_CACHE[chave_memoria] = deepcopy(resultado_local)
        return deepcopy(resultado_local)
