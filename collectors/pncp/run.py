import argparse
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging_config import setup_logging
from config.runtime_settings import DEBUG_LOGS
from collectors.pncp.collector import PNCPCollector


def yyyymmdd(valor):
    if valor:
        return valor
    return date.today().strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="Coletor PNCP incremental")
    parser.add_argument("--endpoint", choices=["publicacao", "proposta"], default="publicacao")
    parser.add_argument("--data-inicial", default=(date.today() - timedelta(days=7)).strftime("%Y%m%d"))
    parser.add_argument("--data-final", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--tamanho-pagina", type=int, default=50)
    parser.add_argument("--modalidade", type=int, default=8)
    parser.add_argument("--max-paginas", type=int, default=1)
    parser.add_argument("--sem-retomar", action="store_true")
    args = parser.parse_args()

    setup_logging(DEBUG_LOGS)
    collector = PNCPCollector()
    resumo = collector.coletar(
        endpoint=args.endpoint,
        data_inicial=yyyymmdd(args.data_inicial),
        data_final=yyyymmdd(args.data_final),
        tamanho_pagina=args.tamanho_pagina,
        codigo_modalidade=args.modalidade,
        max_paginas=args.max_paginas,
        retomar=not args.sem_retomar,
    )
    print(resumo)


if __name__ == "__main__":
    main()

