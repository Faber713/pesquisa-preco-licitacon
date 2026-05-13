# =========================
# CONFIGURAÇÕES GERAIS
# =========================

MODELO_IA = "gpt-4o-mini"


# =========================
# RESULTADOS
# =========================

MAX_RESULTADOS = 80
MIN_RESULTADOS_DESEJADOS = 3


# =========================
# LIMIARES DE SCORE
# =========================

LIMIAR_RIGIDO = 40
LIMIAR_RELAXADO = 20
LIMIAR_AMPLO = 12


# =========================
# REGRAS DE OBRIGATÓRIOS
# =========================

MIN_PCT_OBRIGATORIOS_RIGIDO = 0.30
MIN_PCT_OBRIGATORIOS_RELAXADO = 0.00
MIN_PCT_OBRIGATORIOS_AMPLO = 0.00


# =========================
# LINK LICITACON
# =========================

# Link seguro, sem checksum.
# O LicitaCon não permite limpar filtros pela URL sem gerar erro de sessão.
LINK_BASE_LICITACON = "https://portal.tce.rs.gov.br/aplicprod/f?p=50500:19"


# =========================
# COMPORTAMENTO DA BUSCA
# =========================

ATIVAR_BUSCA_SEM_QUANTIDADE = True

LIMIAR_RELAXADO_SEM_QTD = 45
LIMIAR_AMPLO_SEM_QTD = 35


# =========================
# PESO DO SCORE
# =========================

PESO_TEXTO = 0.40
PESO_OBRIGATORIOS = 0.30
PESO_IMPORTANTES = 0.15
PESO_FRASES = 0.15


# =========================
# PALAVRAS GENÉRICAS
# =========================

TERMOS_GENERICOS = {
    "alicate",
    "equipamento",
    "material",
    "peca",
    "produto",
    "ferramenta",
    "servico",
    "aparelho",
    "maquina",
    "kit",
    "conjunto",
    "rele",
    "sensor",
    "bloco",
    "item"
}


# =========================
# PALAVRAS FRACAS
# =========================

PALAVRAS_FRACAS = {
    "de",
    "do",
    "da",
    "dos",
    "das",
    "com",
    "sem",
    "para",
    "por",
    "em",
    "e",
    "a",
    "o",
    "as",
    "os",
    "tipo",
    "modelo",
    "unidade",
    "produto",
    "material",
    "fornecimento",
    "aquisicao",
    "novo",
    "nova",
    "uso",
    "minimo",
    "maximo",
    "capacidade",
    "conforme",
    "especificacao",
    "tecnica",
    "tecnico",
    "tecnicos"
}