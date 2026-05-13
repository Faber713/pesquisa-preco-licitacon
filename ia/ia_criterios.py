import os
import json
import re
from openai import OpenAI

from utils.config import MODELO_IA, PALAVRAS_FRACAS
from utils.util import normalizar


# =========================
# DESCRIÇÃO SUGERIDA LOCAL
# =========================

def gerar_descricao_sugerida_local(descricao):
    texto = normalizar(descricao)
    palavras = texto.split()

    manter = []

    for p in palavras:
        if p in {"rele", "relé", "fase", "fases", "falta", "neutro", "trifasica", "trifasico"}:
            manter.append(p)

        elif re.match(r"^\d+v$", p):
            manter.append(p)

        elif len(p) >= 4 and p not in PALAVRAS_FRACAS:
            manter.append(p)

    manter = list(dict.fromkeys(manter))

    if "rele" in manter and "falta" in manter and "fase" in manter:
        base = ["rele", "falta", "fase"]

        if "380v" in manter:
            base.append("380v")
        elif "220v" in manter:
            base.append("220v")

        return " ".join(base)

    if len(manter) >= 2:
        return " ".join(manter[:5])

    return descricao


# =========================
# EXTRAÇÃO SEM IA
# =========================

def extrair_criterios_simples(descricao):
    texto = normalizar(descricao)
    palavras = texto.split()

    termos = []

    for p in palavras:
        if len(p) >= 4 and p not in PALAVRAS_FRACAS:
            termos.append(p)

    termos = list(dict.fromkeys(termos))

    frase_principal = " ".join(termos[:2]) if len(termos) >= 2 else " ".join(termos[:1])

    descricao_sugerida = gerar_descricao_sugerida_local(descricao)

    obrigatorios = []
    if frase_principal:
        obrigatorios.append(frase_principal)

    obrigatorios += termos[:4]

    return {
        "termos_obrigatorios": list(dict.fromkeys(obrigatorios))[:8],
        "termos_importantes": termos[4:20],
        "termos_excluir": [],
        "frases_chave": [frase_principal] if frase_principal else [],
        "descricao_resumida": descricao,
        "descricao_sugerida_licitacon": descricao_sugerida
    }


# =========================
# EXTRAÇÃO COM IA
# =========================

def extrair_criterios_com_ia(descricao):
    chave = os.getenv("OPENAI_API_KEY")

    if not chave:
        print("\nOPENAI_API_KEY não encontrada.")
        print("Usando modo simples sem IA.")
        return extrair_criterios_simples(descricao)

    client = OpenAI(api_key=chave)

    prompt = f"""
Você é um assistente técnico especialista em compras públicas e pesquisa de preços no LicitaCon/TCE-RS.

Analise a descrição abaixo e retorne SOMENTE um JSON válido:

Descrição:
{descricao}

Formato obrigatório:

{{
  "termos_obrigatorios": [],
  "termos_importantes": [],
  "termos_excluir": [],
  "frases_chave": [],
  "descricao_resumida": "",
  "descricao_sugerida_licitacon": ""
}}

Regras:
- descricao_sugerida_licitacon deve ter de 2 a 5 palavras.
- Deve preservar o núcleo técnico específico.
- Evite termo genérico sozinho.
- Exemplo ruim: "rele".
- Exemplo ruim: "rele falta".
- Exemplo bom: "rele falta fase".
- Exemplo bom: "rele falta fase 380v".
- Exemplo bom: "rele fotoeletrico".
- Exemplo bom: "bloco temporizador".
- Não invente especificações.
- Normalize sem acento.
- Retorne apenas JSON.
"""

    try:
        resposta = client.chat.completions.create(
            model=MODELO_IA,
            messages=[
                {
                    "role": "system",
                    "content": "Você extrai critérios técnicos para busca de preços públicos."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        conteudo = resposta.choices[0].message.content.strip()
        conteudo = conteudo.replace("```json", "").replace("```", "").strip()

        dados = json.loads(conteudo)

        descricao_sugerida = dados.get("descricao_sugerida_licitacon", "").strip()
        descricao_sugerida_norm = normalizar(descricao_sugerida)

        # Corrige resposta genérica da IA
        if (
            not descricao_sugerida
            or len(descricao_sugerida_norm.split()) < 2
            or descricao_sugerida_norm in {"rele", "rele falta", "bloco", "sensor", "chave"}
        ):
            descricao_sugerida = gerar_descricao_sugerida_local(descricao)

        # Regra especial: relé falta de fase
        texto_original_norm = normalizar(descricao)
        if "rele" in texto_original_norm and "falta" in texto_original_norm and "fase" in texto_original_norm:
            descricao_sugerida = gerar_descricao_sugerida_local(descricao)

        return {
            "termos_obrigatorios": dados.get("termos_obrigatorios", []),
            "termos_importantes": dados.get("termos_importantes", []),
            "termos_excluir": dados.get("termos_excluir", []),
            "frases_chave": dados.get("frases_chave", []),
            "descricao_resumida": dados.get("descricao_resumida", descricao),
            "descricao_sugerida_licitacon": descricao_sugerida
        }

    except Exception as e:
        print("\nErro ao usar IA. Usando modo simples.")
        print(f"Detalhe: {e}")
        return extrair_criterios_simples(descricao)
