#!/usr/bin/env python3
"""
Scraper del Registro Nacional de Personas Desaparecidas y No Localizadas (RNPDNO).
https://consultapublicarnpdno.segob.gob.mx/

Uso:
    python main.py --estado Tabasco --municipio Centro --fecha-inicio 01/01/2022 --fecha-fin 31/12/2024
    python main.py --estado-id 27
    python main.py --all-estados
"""

import argparse
import sys
import os

# Asegurar que el scraper este en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.pipeline import scrape, scrape_all_estados
from scraper.estados import ESTADO_ID_MAP, ESTADOS


def resolve_estado_id(name_or_id: str) -> str:
    """Resuelve ID de estado desde nombre o numero."""
    if name_or_id.isdigit():
        if name_or_id in ESTADOS:
            return name_or_id
        raise ValueError(f"ID de estado invalido: {name_or_id}")

    name_lower = name_or_id.strip().lower()
    if name_lower in ESTADO_ID_MAP:
        return ESTADO_ID_MAP[name_lower]

    # Busqueda parcial
    for name, eid in ESTADO_ID_MAP.items():
        if name_lower in name:
            return eid

    raise ValueError(
        f"Estado no encontrado: {name_or_id}\n"
        f"Estados validos: {', '.join(ESTADOS.values())}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scraper RNPDNO - Personas Desaparecidas en Mexico",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py --estado Tabasco
  python main.py --estado-id 27 --fecha-inicio 01/01/2022 --fecha-fin 31/12/2024
  python main.py --estado Tabasco --municipio 4
  python main.py --all-estados --rows 100 --delay 0.5
  python main.py --folio "JUAN PEREZ" --estado Jalisco
        """,
    )

    # Filtros principales
    parser.add_argument("--estado", help="Nombre del estado (ej: Tabasco, Jalisco)")
    parser.add_argument("--estado-id", help="ID numerico del estado (ej: 27)")
    parser.add_argument(
        "--municipio", default="", help="ID del municipio o alcaldia (vacio = todos)"
    )
    parser.add_argument(
        "--fecha-inicio", default="", help="Fecha inicio (DD/MM/YYYY)"
    )
    parser.add_argument(
        "--fecha-fin", default="", help="Fecha fin (DD/MM/YYYY)"
    )
    parser.add_argument(
        "--folio", default="", help="Busqueda por folio/nombre (min 5 caracteres)"
    )

    # Opciones de scrape
    parser.add_argument(
        "--rows", type=int, default=50, help="Registros por pagina (default: 50)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=0, help="Maximo de paginas (0 = todas)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Segundos entre requests (default: 1.0)"
    )
    parser.add_argument(
        "--output", default="data/resultados", help="Ruta base de salida"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Formato de salida (default: csv)",
    )

    # Modo masivo
    parser.add_argument(
        "--all-estados",
        action="store_true",
        help="Iterar sobre los 32 estados",
    )
    parser.add_argument(
        "--all-dir",
        default="data",
        help="Directorio de salida para --all-estados",
    )

    args = parser.parse_args()

    # Resolver estado
    estado_id = ""
    if args.estado_id:
        estado_id = args.estado_id
    elif args.estado:
        estado_id = resolve_estado_id(args.estado)

    # Modo: todos los estados
    if args.all_estados:
        print("Modo: Todos los estados")
        scrape_all_estados(
            fecha_inicio=args.fecha_inicio,
            fecha_fin=args.fecha_fin,
            rows_per_page=args.rows,
            max_pages_per_estado=args.max_pages,
            output_dir=args.all_dir,
            delay=args.delay,
        )
        return

    # Modo: busqueda especifica
    if not estado_id and not args.folio:
        parser.error("Especifica --estado, --estado-id, o --folio")

    if args.folio and len(args.folio) < 5:
        parser.error("El folio debe tener al menos 5 caracteres")

    print(f"Estado: {ESTADOS.get(estado_id, 'Todos')} (ID: {estado_id or 'N/A'})")
    print(f"Municipio: {args.municipio or 'Todos'}")
    print(f"Fecha inicio: {args.fecha_inicio or 'Sin filtro'}")
    print(f"Fecha fin: {args.fecha_fin or 'Sin filtro'}")
    print(f"Folio: {args.folio or 'Sin filtro'}")
    print(f"Rows/pag: {args.rows} | Max paginas: {args.max_pages or 'Todas'}")
    print()

    records = scrape(
        estado_id=estado_id,
        municipio_id=args.municipio,
        fecha_inicio=args.fecha_inicio,
        fecha_fin=args.fecha_fin,
        folio=args.folio,
        rows_per_page=args.rows,
        max_pages=args.max_pages,
        output_format=args.format,
        output_path=args.output,
        delay=args.delay,
    )

    print(f"\nScraping completado: {len(records)} registros obtenidos.")


if __name__ == "__main__":
    main()
