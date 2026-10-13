"""Punto de entrada: python3 main.py [--fuente IBM]"""
import argparse
from jobhunter.runner import crear_scrapers, procesar_scraper


def main() -> int:
    parser = argparse.ArgumentParser(description="JobHunter multiempresa")
    parser.add_argument(
        "--fuente", action="append", metavar="EMPRESA",
        help="Ejecutar solo una empresa; se puede repetir",
    )
    parser.add_argument(
        "--listar", action="store_true", help="Listar fuentes configuradas",
    )
    args = parser.parse_args()
    scrapers = crear_scrapers()
    if args.listar:
        print("Fuentes disponibles:")
        for scraper in scrapers:
            print(" -", scraper.empresa)
        return 0

    if args.fuente:
        elegidas = set(args.fuente)
        desconocidas = elegidas - {s.empresa for s in scrapers}
        if desconocidas:
            parser.error("Fuentes no configuradas: " + ", ".join(sorted(desconocidas)))
        scrapers = [s for s in scrapers if s.empresa in elegidas]

    print("JobHunter · monitor multiempresa")
    resultados = [procesar_scraper(s) for s in scrapers]
    if not all(resultados):
        print("\nAlgunas fuentes fallaron. Otras se procesaron independientemente.")
        return 1
    print("\nMonitorización terminada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
