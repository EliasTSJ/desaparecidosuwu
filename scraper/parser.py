"""
Parseo y normalizacion de respuestas de la API.
"""

import csv
import json
import os
from datetime import datetime
from typing import Any


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def parse_record(row: dict) -> dict:
    """
    Normaliza un registro individual de la API.
    La API marca registros sin datos como 'CONFIDENCIAL'.
    """
    nombre = _safe_str(row.get("nombre", ""))
    primer_apellido = _safe_str(row.get("primerapellido", ""))
    segundo_apellido = _safe_str(row.get("segundoapellido", ""))

    # Si es confidencial, el nombre viene como 'CONFIDENCIAL'
    if nombre == "CONFIDENCIAL":
        nombre_completo = "CONFIDENCIAL"
    else:
        partes = [nombre, primer_apellido, segundo_apellido]
        nombre_completo = " ".join(p for p in partes if p)

    fecha_hechos_raw = _safe_str(row.get("ffechahechos", ""))
    fecha_nacimiento_raw = _safe_str(row.get("fechanacimiento", ""))

    edad_actual = row.get("edadActual", "")
    if isinstance(edad_actual, str):
        edad_actual = edad_actual
    elif isinstance(edad_actual, (int, float)):
        edad_actual = str(int(edad_actual))

    return {
        "id_victima": _safe_str(row.get("IDvictimadirecta", "")),
        "id_vinculacion": _safe_str(row.get("IDvinculacion", "")),
        "id_reporte": _safe_str(row.get("IDreporte", "")),
        "nombre_completo": nombre_completo,
        "nombre": _safe_str(nombre),
        "primer_apellido": _safe_str(primer_apellido),
        "segundo_apellido": _safe_str(segundo_apellido),
        "sexo": _safe_str(row.get("Sexo", "")),
        "edad_actual": _safe_str(edad_actual),
        "fecha_nacimiento": fecha_nacimiento_raw,
        "fecha_hechos": fecha_hechos_raw,
        "fecha_percato": _safe_str(row.get("ffechapercato", "")),
        "estatus": _safe_str(row.get("EstatusVictima", "")),
        "estado": _safe_str(row.get("estado", "")),
        "municipio": _safe_str(row.get("municipio", "")),
        "dependencia_origen": _safe_str(row.get("dependenciaOrigen", "")),
        "id_dependencia": _safe_str(row.get("iddependenciaorigen", "")),
        "fecha_captura": _safe_str(row.get("fechacaptura", "")),
    }


def parse_search_response(data: dict) -> list[dict]:
    """
    Extrae y normaliza los registros de la respuesta de busqueda.
    """
    records = data.get("data", [])
    return [parse_record(r) for r in records]


def save_csv(records: list[dict], filepath: str):
    """Guarda registros en CSV."""
    if not records:
        print("No hay registros para guardar.")
        return

    fieldnames = list(records[0].keys())
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"Guardados {len(records)} registros en {filepath}")


def save_json(records: list[dict], filepath: str):
    """Guarda registros en JSON."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Guardados {len(records)} registros en {filepath}")
