from util import normalizar


def contem(texto, termo):
    return termo in texto


def contem_algum(texto, termos):
    return any(termo in texto for termo in termos)


def primeira_palavra(texto):
    partes = texto.split()
    return partes[0] if partes else ""


def inicio(texto, qtd=10):
    return " ".join(texto.split()[:qtd])


def validar_produto_eletrico(descricao_busca, descricao_resultado):
    busca = normalizar(descricao_busca)
    resultado = normalizar(descricao_resultado)
    res_inicio = inicio(resultado, 12)
    res_primeira = primeira_palavra(resultado)

    # Ferramentas manuais
    if "alicate" in busca:
        if "alicate" not in resultado:
            return False, "Busca e de alicate, mas resultado nao contem alicate."

        if "crimpar" in busca:
            if res_primeira in {"jogo", "kit"}:
                return False, "Busca alicate unitario para crimpar, mas resultado e jogo/kit."

            if contem_algum(resultado, ["desencapador", "decapador"]) and not contem_algum(resultado, ["crimpar", "crimpagem", "crimpador", "prensar", "terminal", "terminais"]):
                return False, "Busca alicate para crimpar, mas resultado e desencapador/decapador."

            if "universal" in resultado and not contem_algum(resultado, ["crimpar", "crimpagem", "crimpador", "prensar", "terminal", "terminais"]):
                return False, "Busca alicate para crimpar, mas resultado e alicate universal."

            conectores_rede = [
                "rj45", "rj 45", "rj11", "rj 11", "rj12", "rj 12",
                "cat5", "cat6", "cat 5", "cat 6", "rede", "ethernet",
                "telefonico", "telefone", "keystone", "8p8c", "6p6c",
                "4p4c", "modular"
            ]

            busca_e_rede = contem_algum(busca, conectores_rede)
            resultado_e_rede = contem_algum(resultado, conectores_rede)

            if not busca_e_rede and resultado_e_rede:
                return False, "Busca alicate para terminais/ilhos, mas resultado e para RJ/rede/telefone."

            if contem_algum(busca, ["terminal", "terminais", "ilhos", "tubolar"]):
                generico_aceitavel = resultado.strip() in {
                    "alicate para crimpar",
                    "alicate crimpar",
                }
                resultado_tem_especificacao_proxima = (
                    contem_algum(resultado, ["ilhos", "tubolar"])
                    or ("0 5" in resultado and "16" in resultado)
                    or ("0 25" in resultado and "10" in resultado)
                )

                if "automotivo" in resultado or "automotivos" in resultado:
                    return False, "Busca alicate para terminais ilhos/tubolar, mas resultado e para terminal automotivo."

                if contem_algum(resultado, ["desencapador", "decapador", "descascador"]) and not resultado_tem_especificacao_proxima:
                    return False, "Busca alicate para ilhos/tubolar, mas resultado e desencapador/descascador sem especificacao compativel."

                if contem_algum(resultado, ["prensa", "prensar"]) and not resultado_tem_especificacao_proxima:
                    return False, "Busca alicate para ilhos/tubolar, mas resultado de prensa terminal nao traz especificacao compativel."

                resultado_terminal_generico = (
                    contem_algum(resultado, ["terminal", "terminais", "ilhos", "tubolar"])
                    or generico_aceitavel
                )

                if not resultado_terminal_generico:
                    return False, "Busca alicate para terminais/ilhos, mas resultado nao indica terminais ou e generico aceitavel."

        subtipos = [
            (["amperimetro"], ["amperimetro"]),
            (["crimpar"], ["crimpar", "crimpagem", "crimpador", "prensar", "terminal", "terminais"]),
            (["corte"], ["corte", "cortar", "cortador"]),
            (["desencapador"], ["desencapador", "decapador", "decapagem"]),
            (["universal"], ["universal"]),
        ]

        for gatilhos, aceitos in subtipos:
            if contem_algum(busca, gatilhos) and not contem_algum(resultado, aceitos):
                return False, "Subtipo de alicate incompatavel."

    if "escada" in busca:
        if "escada" not in resultado:
            return False, "Busca e de escada, mas resultado nao contem escada."

    if "estilete" in busca:
        if "estilete" not in resultado:
            return False, "Busca e de estilete, mas resultado nao contem estilete."

    if "ferro de solda" in busca:
        if "ferro" not in resultado or "solda" not in resultado:
            return False, "Busca e de ferro de solda, mas resultado nao contem ferro de solda."

    if "passador" in busca and "fio" in busca:
        if "passador" not in resultado or "fio" not in resultado:
            return False, "Busca e de passador de fio, mas resultado nao contem passador de fio."

    if "trena" in busca:
        if "trena" not in resultado:
            return False, "Busca e de trena, mas resultado nao contem trena."
        if "laser" in busca and "laser" not in resultado:
            return False, "Busca e de trena laser, mas resultado nao contem laser."

    if "nivel" in busca and "aluminio" in busca:
        if "nivel" not in resultado or "aluminio" not in resultado:
            return False, "Busca e de nivel de aluminio, mas resultado nao contem nivel de aluminio."

    # Chaves
    if "chave" in busca:
        if "chave" not in resultado and "contatora" not in resultado and "contactor" not in resultado:
            return False, "Busca e de chave, mas resultado nao contem chave/contator."

        regras_chave = [
            (["boia"], ["boia", "boia de nivel", "nivel"]),
            (["contactora", "contatora"], ["contactora", "contatora", "contator"]),
            (["allen"], ["allen", "hexagonal"]),
            (["teste"], ["teste"]),
            (["corrente", "tubos"], ["corrente", "tubo", "tubos"]),
            (["fenda", "phillips"], ["fenda", "phillips"]),
        ]

        for gatilhos, aceitos in regras_chave:
            if all(g in busca for g in gatilhos) and not contem_algum(resultado, aceitos):
                return False, "Subtipo de chave incompatavel."

    # Protecao eletrica
    if "disjuntor" in busca:
        if "disjuntor" not in resultado:
            return False, "Busca e de disjuntor, mas resultado nao contem disjuntor."

    if "diferencial" in busca or "30ma" in busca or "dr " in f"{busca} ":
        if not contem_algum(resultado, ["dr", "diferencial", "residual", "idr"]):
            return False, "Busca e de DR/diferencial, mas resultado nao contem DR/diferencial."

    if "tripolar" in busca and not contem_algum(resultado, ["tripolar", "3p", "tetrapolar"]):
        return False, "Busca informa tripolar, mas resultado nao apresenta tripolar/3P."

    if ("bipolar" in busca or "2p" in busca) and not contem_algum(resultado, ["bipolar", "2p"]):
        return False, "Busca informa bipolar/2P, mas resultado nao apresenta bipolar/2P."

    if ("unipolar" in busca or "monopolar" in busca) and not contem_algum(resultado, ["unipolar", "monopolar", "1p"]):
        return False, "Busca informa unipolar/monopolar, mas resultado nao apresenta unipolar/monopolar/1P."

    # Rele e temporizacao
    if "rele" in busca or "rel " in f"{busca} ":
        if "base" in busca and not ("base" in resultado and contem_algum(resultado, ["rele", "fotocontrolador", "fotoeletrico"])):
            return False, "Busca e de base para rele, mas resultado nao e base de rele."

        if "falta" in busca and "fase" in busca:
            if not ("rele" in resultado and "falta" in resultado and "fase" in resultado):
                return False, "Busca e de rele falta de fase, mas resultado nao contem falta de fase."

        if "termico" in busca or "sobrecarga" in busca:
            if not ("rele" in resultado and contem_algum(resultado, ["termico", "sobrecarga"])):
                return False, "Busca e de rele termico/sobrecarga, mas resultado nao corresponde."

        if contem_algum(busca, ["fotocelula", "fotoeletrico", "fotocontrolador"]):
            if not contem_algum(resultado, ["fotocelula", "fotoeletrico", "fotocontrolador"]):
                return False, "Busca e de rele fotoeletrico/fotocelula, mas resultado nao corresponde."

    if "temporizador" in busca or "timer" in busca:
        timer_no_nucleo = contem_algum(
            res_inicio,
            ["timer", "temporizador", "programador", "rele temporizador", "bloco temporizador"]
        )
        if not timer_no_nucleo:
            return False, "Timer/temporizador aparece apenas como acessorio."

        bloqueados_timer = {
            "ar", "aparelho", "condicionador", "concentrador", "forno",
            "fritadeira", "torneira", "secadora", "seladora", "jogo"
        }
        if res_primeira in bloqueados_timer:
            return False, "Timer/temporizador aparece em outro produto principal."

    # Capacitores
    if "capacitor" in busca:
        if "capacitor" not in resultado:
            return False, "Busca e de capacitor, mas resultado nao contem capacitor."
        if "arranque" in busca and not contem_algum(resultado, ["arranque", "partida"]):
            return False, "Busca capacitor de arranque, mas resultado nao indica arranque/partida."
        if "permanente" in busca and "permanente" not in resultado:
            return False, "Busca capacitor permanente, mas resultado nao indica permanente."

    # Iluminacao publica
    if "luminaria" in busca:
        if "luminaria" not in resultado:
            return False, "Busca e de luminaria, mas resultado nao contem luminaria."
        if "publica" in busca and not contem_algum(resultado, ["publica", "iluminacao publica"]):
            return False, "Busca luminaria publica, mas resultado nao indica uso publico."
        if "led" in busca and "led" not in resultado:
            return False, "Busca luminaria LED, mas resultado nao contem LED."

    if "braco" in busca and "luminaria" in busca:
        if "braco" not in resultado or "luminaria" not in resultado:
            return False, "Busca e de braco para luminaria, mas resultado nao corresponde."

    if "cinta" in busca or "abracadeira" in busca:
        if not contem_algum(resultado, ["cinta", "abracadeira"]):
            return False, "Busca e de cinta/abracadeira, mas resultado nao contem cinta/abracadeira."
        if "nylon" in busca and "nylon" not in resultado:
            return False, "Busca abracadeira de nylon, mas resultado nao contem nylon."

    # Cabos, fios e terminais
    if "cabo pp" in busca:
        if "cabo" not in resultado or "pp" not in resultado:
            return False, "Busca e de cabo PP, mas resultado nao contem cabo PP."

    if "fio" in busca or "flexivel" in busca:
        if not contem_algum(resultado, ["fio", "cabo", "condutor"]):
            return False, "Busca e de fio/cabo, mas resultado nao contem fio/cabo/condutor."
        cores = ["azul", "preto", "vermelho", "branco"]
        for cor in cores:
            if cor in busca and cor not in resultado:
                return False, "Cor do fio/cabo incompatavel."

    if "terminal" in busca:
        if "terminal" not in resultado:
            return False, "Busca e de terminal, mas resultado nao contem terminal."
        for subtipo in ["femea", "olhal", "tubolar", "ilhos"]:
            if subtipo in busca and subtipo not in resultado:
                return False, "Subtipo de terminal incompatavel."

    if "conector" in busca:
        if "conector" not in resultado:
            return False, "Busca e de conector, mas resultado nao contem conector."
        if "splitbolt" in busca and not contem_algum(resultado, ["splitbolt", "split bolt"]):
            return False, "Busca conector splitbolt, mas resultado nao corresponde."
        if "derivacao" in busca and not contem_algum(resultado, ["derivacao", "perfurante", "piercing"]):
            return False, "Busca conector de derivacao/perfurante, mas resultado nao corresponde."

    if "plug" in busca:
        if "plug" not in resultado and "tomada" not in resultado:
            return False, "Busca e de plug/tomada, mas resultado nao corresponde."

    if "trilho" in busca and "disjuntor" in busca:
        if "trilho" not in resultado:
            return False, "Busca trilho para disjuntor, mas resultado nao contem trilho."

    # Fixadores, brocas, fitas e consumiveis
    if "arruela" in busca and "arruela" not in resultado:
        return False, "Busca e de arruela, mas resultado nao contem arruela."

    if "porca" in busca and "porca" not in resultado:
        return False, "Busca e de porca, mas resultado nao contem porca."

    if "parafuso" in busca and "parafuso" not in resultado:
        return False, "Busca e de parafuso, mas resultado nao contem parafuso."

    if "broca" in busca:
        if "broca" not in resultado:
            return False, "Busca e de broca, mas resultado nao contem broca."
        for material in ["porcelanato", "aco rapido", "videa", "mourao"]:
            if material in busca and material not in resultado:
                return False, "Tipo/material da broca incompatavel."

    if "bucha" in busca and "bucha" not in resultado:
        return False, "Busca e de bucha, mas resultado nao contem bucha."

    if "fita" in busca:
        if "fita" not in resultado:
            return False, "Busca e de fita, mas resultado nao contem fita."
        for subtipo in ["autofusao", "dupla face", "isolante", "metrica"]:
            if subtipo in busca and subtipo not in resultado:
                return False, "Subtipo de fita incompatavel."

    if "desengripante" in busca and "desengripante" not in resultado:
        return False, "Busca e de desengripante, mas resultado nao contem desengripante."

    if "limpa contato" in busca:
        if not ("limpa" in resultado and "contato" in resultado):
            return False, "Busca e de limpa contato, mas resultado nao contem limpa contato."

    if "solda estanho" in busca:
        if not ("solda" in resultado and "estanho" in resultado):
            return False, "Busca e de solda estanho, mas resultado nao corresponde."

    if "caixa" in busca:
        if "caixa" not in resultado and "maleta" not in resultado:
            return False, "Busca e de caixa/maleta, mas resultado nao corresponde."
        if "painel eletrico" in busca and not contem_algum(resultado, ["painel", "eletrico", "comando"]):
            return False, "Busca caixa para painel eletrico, mas resultado nao corresponde."
        if "ferramentas" in busca and not contem_algum(resultado, ["ferramenta", "ferramentas", "maleta"]):
            return False, "Busca caixa para ferramentas, mas resultado nao corresponde."

    if "pilha" in busca and "pilha" not in resultado:
        return False, "Busca e de pilha, mas resultado nao contem pilha."

    if "bateria" in busca and "bateria" not in resultado:
        return False, "Busca e de bateria, mas resultado nao contem bateria."

    if "luva" in busca:
        if "luva" not in resultado:
            return False, "Busca e de luva, mas resultado nao contem luva."
        if "nylon" in busca and "nylon" not in resultado:
            return False, "Busca luva de nylon, mas resultado nao contem nylon."
        if "latex" in busca and "latex" not in resultado:
            return False, "Busca luva com latex, mas resultado nao contem latex."

    return True, ""
