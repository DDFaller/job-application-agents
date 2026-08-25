from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from .matching import load_profile
from .scraper import DEFAULT_SEED_URLS, ScrapeOptions, scrape_compatible_jobs, write_result


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = PROJECT_ROOT / "config" / "profile.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coleta vagas públicas do Welcome to the Jungle e mantém somente as compatíveis."
    )
    parser.add_argument("--pages", type=int, default=2, help="Páginas por fonte de descoberta (padrão: 2).")
    parser.add_argument("--max-jobs", type=int, default=60, help="Máximo de páginas de vaga a abrir (padrão: 60).")
    parser.add_argument("--min-score", type=int, help="Sobrescreve temporariamente o corte do perfil.")
    parser.add_argument("--delay", type=float, default=1.5, help="Intervalo entre requisições, em segundos.")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout por página, em segundos.")
    parser.add_argument("--headed", action="store_true", help="Exibe o Chromium durante a coleta.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="Arquivo JSON do perfil de filtro.")
    parser.add_argument("--output", type=Path, help="Caminho do JSON de saída.")
    parser.add_argument(
        "--seed-url",
        action="append",
        dest="seed_urls",
        help="Página pública adicional/substitutiva de descoberta; pode ser repetida.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.pages < 1 or args.max_jobs < 1:
        raise SystemExit("--pages e --max-jobs precisam ser maiores que zero.")
    if args.min_score is not None and not 0 <= args.min_score <= 100:
        raise SystemExit("--min-score deve estar entre 0 e 100.")
    if args.delay < 0:
        raise SystemExit("--delay não pode ser negativo.")

    profile = load_profile(args.profile.resolve())
    output = args.output or PROJECT_ROOT / "output" / f"compatible-jobs-{datetime.now():%Y-%m-%d_%H%M%S}.json"
    options = ScrapeOptions(
        pages=args.pages,
        max_jobs=args.max_jobs,
        delay_seconds=args.delay,
        timeout_ms=args.timeout * 1000,
        headed=args.headed,
        minimum_score=args.min_score,
        seed_urls=args.seed_urls or list(DEFAULT_SEED_URLS),
    )

    print(f"Perfil: {profile['profile_version']} | corte: {args.min_score or profile['minimum_score']}")
    print(f"Descoberta: {len(options.seed_urls)} páginas-base × {options.pages} página(s)")
    payload = asyncio.run(scrape_compatible_jobs(profile, options))
    write_result(payload, output.resolve())
    print(
        f"Concluído: {payload['compatible_count']} compatíveis de "
        f"{payload['processed_count']} processadas — {output.resolve()}"
    )
    if payload["errors"]:
        print(f"Avisos de coleta: {len(payload['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

