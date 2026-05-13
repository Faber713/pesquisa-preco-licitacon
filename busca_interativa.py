import pandas as pd
from datetime import datetime

from utils.config import MIN_RESULTADOS_DESEJADOS
from utils.util import escolher_arquivo, converter_numero, normalizar
from ia.ia_criterios import extrair_criterios_com_ia
from search.busca import buscar_item, juntar_resultados
from reports.html_saida import salvar_html


def main():
    print("\nBUSCA INTELIGENTE LICITACON COM IA\n")

    arquivo = escolher_arquivo()
    if not arquivo:
        return

    print(f"\nArquivo selecionado:\n{arquivo}")

    try:
        df = pd.read_csv(arquivo, sep=";", encoding="utf-8", dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(arquivo, sep=";", encoding="latin1", dtype=str)

    print(f"\nTotal de linhas carregadas: {len(df)}")

    descricao_busca = input("\nCole a descrição do item que deseja pesquisar:\n> ").strip()

    qtd_min = converter_numero(input("\nQuantidade mínima: "))
    qtd_max = converter_numero(input("Quantidade máxima: "))

    if qtd_min is None or qtd_max is None:
        print("\nQuantidade inválida.")
        return

    if qtd_min > qtd_max:
        print("\nQuantidade mínima não pode ser maior que a máxima.")
        return

    print("\nAnalisando descrição com IA...")
    criterios = extrair_criterios_com_ia(descricao_busca)

    print("\nCRITÉRIOS EXTRAÍDOS:")
    print(f"Descrição sugerida LicitaCon: {criterios.get('descricao_sugerida_licitacon', '')}")
    print(f"Obrigatórios: {', '.join(criterios.get('termos_obrigatorios', []))}")
    print(f"Importantes: {', '.join(criterios.get('termos_importantes', []))}")

    resultados_rigido = buscar_item(df, descricao_busca, qtd_min, qtd_max, criterios, "rigido")
    resultados_relaxado = buscar_item(df, descricao_busca, qtd_min, qtd_max, criterios, "relaxado")
    resultados_amplo = buscar_item(df, descricao_busca, qtd_min, qtd_max, criterios, "amplo")

    resultados_temp = juntar_resultados(
        resultados_rigido,
        resultados_relaxado,
        resultados_amplo
    )

    resultados_relaxado_sem_qtd = []
    resultados_amplo_sem_qtd = []

    if len(resultados_temp) < MIN_RESULTADOS_DESEJADOS:
        print("\nPoucos resultados encontrados. Rodando busca complementar sem eliminar por quantidade...")

        resultados_relaxado_sem_qtd = buscar_item(
            df, descricao_busca, qtd_min, qtd_max, criterios, "relaxado", ignorar_quantidade=True
        )

        resultados_amplo_sem_qtd = buscar_item(
            df, descricao_busca, qtd_min, qtd_max, criterios, "amplo", ignorar_quantidade=True
        )

        resultados = juntar_resultados(
            resultados_rigido,
            resultados_relaxado,
            resultados_amplo,
            resultados_relaxado_sem_qtd,
            resultados_amplo_sem_qtd
        )
    else:
        resultados = resultados_temp

    agora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_item = normalizar(criterios.get("descricao_sugerida_licitacon", "pesquisa")).replace(" ", "_")[:40]
    nome_base = f"LICITACON_{nome_item}_{agora}"

    nome_html = salvar_html(
        descricao_busca=descricao_busca,
        qtd_min=qtd_min,
        qtd_max=qtd_max,
        criterios=criterios,
        resultados=resultados,
        nome_base=nome_base
    )

    print(f"\nResultados rígidos: {len(resultados_rigido)}")
    print(f"Resultados relaxados: {len(resultados_relaxado)}")
    print(f"Resultados amplos: {len(resultados_amplo)}")

    if resultados_relaxado_sem_qtd or resultados_amplo_sem_qtd:
        print(f"Resultados complementares relaxados sem quantidade: {len(resultados_relaxado_sem_qtd)}")
        print(f"Resultados complementares amplos sem quantidade: {len(resultados_amplo_sem_qtd)}")

    print(f"Total sem duplicar: {len(resultados)}")
    print(f"Arquivo HTML salvo com sucesso: {nome_html}")


if __name__ == "__main__":
    main()
