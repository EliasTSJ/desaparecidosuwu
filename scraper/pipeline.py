"""
Pipeline principal de scraping.
Orquesta: autenticacion → busqueda → paginacion → exportacion.
"""

import math
import time
from datetime import datetime
from typing import Any

from tqdm import tqdm

from .api import ConsultaAPI
from .parser import parse_search_response, save_csv, save_json


def build_filtros(
    estado_id: str = "",
    municipio_id: str = "",
    fecha_inicio: str = "",
    fecha_fin: str = "",
    folio: str = "",
) -> dict:
    """
    Construye el objeto filtros tal como espera la API.
    El frontend envia: {folio, rango, estado, municipio, rango_fecha}
    """
    filtros: dict[str, Any] = {
        "folio": folio,
        "rango": "",
        "estado": estado_id,
        "municipio": municipio_id,
        "rango_fecha": "",
    }

    # rango_fecha: el datepicker devuelve [startDate, endDate]
    # Date objects se serializan como ISO strings via JSON.stringify
    if fecha_inicio and fecha_fin:
        filtros["rango_fecha"] = [fecha_inicio, fecha_fin]
    elif fecha_inicio:
        filtros["rango_fecha"] = [fecha_inicio, fecha_inicio]

    return filtros


def scrape(
    estado_id: str = "",
    municipio_id: str = "",
    fecha_inicio: str = "",
    fecha_fin: str = "",
    folio: str = "",
    rows_per_page: int = 50,
    max_pages: int = 0,
    output_format: str = "csv",
    output_path: str = "data/resultados",
    include_photos: bool = False,
    delay: float = 1.0,
) -> list[dict]:
    """
    Ejecuta el scraping completo.

    Args:
        estado_id: ID del estado (vacio = todos)
        municipio_id: ID del municipio (vacio = todos)
        fecha_inicio: Fecha inicio en formato DD/MM/YYYY o YYYY-MM-DD
        fecha_fin: Fecha fin en formato DD/MM/YYYY o YYYY-MM-DD
        folio: Folio de busqueda (texto)
        rows_per_page: Registros por pagina
        max_pages: Maximo de paginas (0 = todas)
        output_format: 'csv' o 'json'
        output_path: Ruta base para guardar
        include_photos: Si se descargan fotos
        delay: Segundos entre requests

    Returns:
        Lista de registros parseados
    """
    api = ConsultaAPI(preset="chrome-latest")

    try:
        # 1. Obtener token
        print("[1/4] Obteniendo token de sesion...")
        token = api.get_token()
        print(f"       Token obtenido: {token[:30]}...")

        # 2. Contar registros
        print("[2/4] Contando registros totales...")
        filtros = build_filtros(estado_id, municipio_id, fecha_inicio, fecha_fin, folio)
        total = api.get_count(filtros)
        print(f"       Total de registros: {total}")

        if total == 0:
            print("       No hay registros para estos filtros.")
            return []

        # 3. Paginar
        total_pages = math.ceil(total / rows_per_page)
        if max_pages and max_pages < total_pages:
            total_pages = max_pages

        print(f"[3/4] Descargando {total_pages} paginas ({rows_per_page} registros/pag)...")

        all_records: list[dict] = []
        for page in tqdm(range(1, total_pages + 1), desc="Paginas"):
            try:
                data = api.search_page(filtros, rows=rows_per_page, page=page)
                records = parse_search_response(data)
                all_records.extend(records)
            except Exception as e:
                print(f"       Error en pagina {page}: {e}")
                continue

            if page < total_pages and delay > 0:
                time.sleep(delay)

        print(f"       Total descargado: {len(all_records)} registros")

        # 4. Guardar
        print("[4/4] Guardando resultados...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"{output_path}_{timestamp}.{output_format}"

        if output_format == "csv":
            save_csv(all_records, path)
        else:
            save_json(all_records, path)

        return all_records

    finally:
        api.close()


def scrape_all_estados(
    fecha_inicio: str = "",
    fecha_fin: str = "",
    rows_per_page: int = 50,
    max_pages_per_estado: int = 0,
    output_dir: str = "data",
    delay: float = 1.0,
):
    """
    Itera sobre todos los estados (1-32, excluyendo 'Se Desconoce').
    Genera un archivo CSV por estado.
    """
    from .estados import ESTADOS

    api = ConsultaAPI(preset="chrome-latest")

    try:
        print("[Token] Obteniendo token de sesion...")
        token = api.get_token()
        print(f"        Token: {token[:30]}...")

        for estado_id, estado_nombre in ESTADOS.items():
            if estado_id == "33":  # Saltar 'Se Desconoce'
                continue

            print(f"\n{'='*60}")
            print(f"Estado {estado_id}: {estado_nombre}")
            print(f"{'='*60}")

            # Contar
            filtros = build_filtros(estado_id, "", fecha_inicio, fecha_fin, "")
            total = api.get_count(filtros)
            print(f"  Total registros: {total}")

            if total == 0:
                print(f"  Sin registros, saltando...")
                continue

            total_pages = math.ceil(total / rows_per_page)
            if max_pages_per_estado and max_pages_per_estado < total_pages:
                total_pages = max_pages_per_estado

            all_records = []
            for page in tqdm(range(1, total_pages + 1), desc=f"  {estado_nombre}"):
                try:
                    data = api.search_page(filtros, rows=rows_per_page, page=page)
                    records = parse_search_response(data)
                    all_records.extend(records)
                except Exception as e:
                    print(f"  Error pagina {page}: {e}")
                    continue

                if page < total_pages and delay > 0:
                    time.sleep(delay)

            safe_name = estado_nombre.replace(" ", "_").lower()
            path = f"{output_dir}/{safe_name}.csv"
            save_csv(all_records, path)

    finally:
        api.close()
