"""
Pipeline robusto de scraping con tolerancia a fallos.

Componentes:
- TokenManager: renovacion automatica de JWT cada 55 min
- YearFinder: busqueda binaria del primer anio con datos (evita iterar 126 anios)
- SmartChunker: chunking anio -> mes -> quincena segun densidad
- RetryManager: 5 reintentos con backoff exponencial + jitter
- CheckpointManager: CSV incremental + reanudacion desde checkpoint
- PageValidator: deteccion de truncamiento del servidor
- IntegrityReport: validacion count vs recuperado
"""

import asyncio
import calendar
import csv
import json
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .api_httpx import ConsultaAPIHttpx
from .parser import parse_search_response
from .pipeline import build_filtros

DEFAULT_CHUNK_LIMIT = 2000
DEFAULT_ROWS_PER_PAGE = 1000
DEFAULT_MAX_RETRIES = 5
DEFAULT_TOKEN_TTL = 3300
DELAY_BETWEEN_PAGES = 0.3


# ---------------------------------------------------------------------------
# TokenManager
# ---------------------------------------------------------------------------

class TokenManager:
    """Envuelve un ConsultaAPIHttpx y renueva el JWT antes de que expire."""

    def __init__(self, api: ConsultaAPIHttpx):
        self._api = api
        self._token_at: float = 0

    async def ensure_token(self):
        if time.time() - self._token_at > DEFAULT_TOKEN_TTL:
            await self._api.get_token()
            self._token_at = time.time()

    async def get_count(self, filtros: dict) -> int:
        await self.ensure_token()
        last_error = None
        for attempt in range(DEFAULT_MAX_RETRIES + 1):
            try:
                return await self._api.get_count(filtros)
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if attempt < DEFAULT_MAX_RETRIES and any(
                    k in msg for k in ("econn", "timeout", "refused", "reset", "read", "unexpected")
                ):
                    wait = (2 ** attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(wait)
                    await self.refresh()
                    continue
                raise
        raise last_error

    async def search_page(self, filtros: dict, rows: int, page: int) -> dict:
        await self.ensure_token()
        return await self._api.search_page(filtros, rows=rows, page=page)

    async def refresh(self):
        await self._api.refresh()
        self._token_at = time.time()


# ---------------------------------------------------------------------------
# YearFinder (busqueda binaria del primer anio con datos)
# ---------------------------------------------------------------------------

async def find_first_year_with_data(
    api: TokenManager,
    estado_id: str,
    fecha_fin: str,
    total_full: int,
) -> Optional[int]:
    """
    Busqueda binaria inversa para encontrar el primer anio que contiene
    registros. Evita iterar 126 anios desde 1900 cuando los datos
    empiezan ~2006.

    Retorna el anio (ej: 2006) o None si total_full == 0.
    """
    if total_full == 0:
        return None

    today = datetime.now()
    lo, hi = 1900, today.year

    while lo < hi:
        mid = (lo + hi) // 2
        fi = f"{mid}-01-01"
        filtros = build_filtros(
            estado_id=estado_id, fecha_inicio=fi, fecha_fin=fecha_fin
        )
        count = await api.get_count(filtros)

        if count == total_full:
            lo = mid + 1
        else:
            hi = mid

    first_year = max(1900, lo - 1)
    return first_year


# ---------------------------------------------------------------------------
# SmartChunker (chunking anio -> mes)
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    fecha_inicio: str
    fecha_fin: str
    expected_count: int = 0

    @property
    def key(self) -> str:
        return f"{self.fecha_inicio}_{self.fecha_fin}"


async def build_chunks(
    api: TokenManager,
    estado_id: str,
    fecha_inicio: str,
    fecha_fin: str,
    chunk_limit: int = DEFAULT_CHUNK_LIMIT,
) -> list[Chunk]:
    """
    Construye una lista de chunks donde cada uno contiene <= chunk_limit
    registros. Estrategia: anio -> mes -> quincena.
    """
    filtros = build_filtros(
        estado_id=estado_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
    )
    total = await api.get_count(filtros)

    if total == 0:
        return []
    if total <= chunk_limit:
        return [Chunk(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, expected_count=total)]

    start_year = datetime.strptime(fecha_inicio, "%Y-%m-%d").year
    end_date = datetime.strptime(fecha_fin, "%Y-%m-%d")
    end_year = end_date.year

    chunks: list[Chunk] = []
    for year in range(start_year, end_year + 1):
        y_fi = f"{year}-01-01"
        y_ff = fecha_fin if year == end_year else f"{year}-12-31"

        y_filtros = build_filtros(
            estado_id=estado_id, fecha_inicio=y_fi, fecha_fin=y_ff
        )
        y_count = await api.get_count(y_filtros)

        if y_count == 0:
            continue
        if y_count <= chunk_limit:
            chunks.append(Chunk(fecha_inicio=y_fi, fecha_fin=y_ff, expected_count=y_count))
        else:
            month_chunks = await _split_year_into_months(
                api, estado_id, year, end_date, chunk_limit, fecha_fin
            )
            chunks.extend(month_chunks)

    return chunks


async def _split_year_into_months(
    api: TokenManager,
    estado_id: str,
    year: int,
    end_date: datetime,
    chunk_limit: int,
    global_fecha_fin: str,
) -> list[Chunk]:
    """Divide un anio denso en chunks mensuales."""
    chunks: list[Chunk] = []
    for month in range(1, 13):
        if year == end_date.year and month > end_date.month:
            break

        last_day = calendar.monthrange(year, month)[1]
        m_fi = f"{year}-{month:02d}-01"
        m_ff = (
            global_fecha_fin
            if (year == end_date.year and month == end_date.month)
            else f"{year}-{month:02d}-{last_day}"
        )

        m_filtros = build_filtros(
            estado_id=estado_id, fecha_inicio=m_fi, fecha_fin=m_ff
        )
        m_count = await api.get_count(m_filtros)

        if m_count == 0:
            continue
        if m_count <= chunk_limit:
            chunks.append(Chunk(fecha_inicio=m_fi, fecha_fin=m_ff, expected_count=m_count))
        else:
            # Caso extremo: quincenas (raro en este dataset)
            for start_day in (1, 16):
                end_day = min(last_day, start_day + 14)
                s_fi = f"{year}-{month:02d}-{start_day:02d}"
                s_ff = (
                    global_fecha_fin
                    if (year == end_date.year and month == end_date.month)
                    else f"{year}-{month:02d}-{end_day:02d}"
                )
                s_filtros = build_filtros(
                    estado_id=estado_id, fecha_inicio=s_fi, fecha_fin=s_ff
                )
                s_count = await api.get_count(s_filtros)
                if s_count > 0:
                    chunks.append(Chunk(fecha_inicio=s_fi, fecha_fin=s_ff, expected_count=s_count))

    return chunks


# ---------------------------------------------------------------------------
# RetryManager
# ---------------------------------------------------------------------------

async def fetch_page_with_retry(
    api: TokenManager,
    filtros: dict,
    page: int,
    rows: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Busca una pagina con backoff exponencial + jitter."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            await api.ensure_token()
            return await api.search_page(filtros, rows=rows, page=page)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(wait)
                await api.refresh()
    raise last_error


# ---------------------------------------------------------------------------
# PageValidator
# ---------------------------------------------------------------------------

class PageValidator:
    """Detecta si el servidor devuelve menos registros de los solicitados."""

    def __init__(self, expected_rows: int):
        self.expected_rows = expected_rows
        self.truncation_detected = False

    def validate(self, page: int, record_count: int, is_last_page: bool):
        if not is_last_page and record_count < self.expected_rows:
            self.truncation_detected = True


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """
    Gestiona scraping resumible:

    - estado_{id}.csv        : archivo principal (append por chunk completado)
    - estado_{id}.tmp.jsonl  : registros temporales del chunk en progreso
    - estado_{id}.checkpoint.json: tracking de chunks y paginas completadas

    Al reiniciar, los chunks ya completados se saltan y el chunk en progreso
    retoma desde la pagina donde se quedo.
    """

    def __init__(self, estado_id: str, output_dir: str = "data"):
        self.estado_id = estado_id
        self.output_dir = output_dir
        self.csv_path = os.path.join(output_dir, f"estado_{estado_id}.csv")
        self.tmp_path = os.path.join(output_dir, f"estado_{estado_id}.tmp.jsonl")
        self.ckpt_path = os.path.join(output_dir, f"estado_{estado_id}.checkpoint.json")

        os.makedirs(output_dir, exist_ok=True)
        self.state = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.ckpt_path):
            with open(self.ckpt_path) as f:
                return json.load(f)
        return {
            "total_expected": 0,
            "total_saved": 0,
            "chunks_done": [],
            "chunk_in_progress": None,
            "pages_done": [],
            "failed_pages": [],
            "truncation_detected": False,
        }

    def _save(self):
        with open(self.ckpt_path, "w") as f:
            json.dump(self.state, f)

    def is_chunk_done(self, chunk_key: str) -> bool:
        return chunk_key in self.state["chunks_done"]

    def clean(self):
        """Elimina CSV y checkpoint antiguos para empezar scrape fresco."""
        for path in (self.csv_path, self.tmp_path, self.ckpt_path):
            if os.path.exists(path):
                os.remove(path)
        self.state = self._load()

    def is_complete(self) -> bool:
        return (
            self.state["total_expected"] > 0
            and self.state["total_saved"] >= self.state["total_expected"]
        )

    def set_expected(self, total: int):
        self.state["total_expected"] = total
        self._save()

    def get_conf_count(self) -> int:
        return self.state.get("conf_count", 0)

    def set_conf_count(self, count: int):
        self.state["conf_count"] = count
        self._save()

    def get_pages_done(self) -> set[int]:
        return set(self.state["pages_done"])

    def ensure_chunk_started(self, chunk_key: str):
        """Inicializa o reanuda un chunk. Solo limpia si es un chunk nuevo."""
        if self.state["chunk_in_progress"] != chunk_key:
            self.state["chunk_in_progress"] = chunk_key
            self.state["pages_done"] = []
            if os.path.exists(self.tmp_path):
                os.remove(self.tmp_path)
            self._save()

    def save_page(self, page: int, records: list[dict]):
        """Guarda una pagina de registros al archivo temporal y actualiza checkpoint."""
        self.state["pages_done"].append(page)
        conf_in_page = sum(1 for r in records if r.get("nombre") == "CONFIDENCIAL")
        self.state["conf_saved_in_chunk"] = self.state.get("conf_saved_in_chunk", 0) + conf_in_page
        with open(self.tmp_path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._save()

    def mark_page_failed(self, page: int):
        """Registra una pagina que fallo todos los reintentos."""
        self.state["failed_pages"].append(page)
        self._save()

    def mark_truncation(self):
        self.state["truncation_detected"] = True
        self._save()

    def finish_chunk(self):
        """Finaliza el chunk en progreso: consolida registros al CSV principal."""
        chunk_key = self.state["chunk_in_progress"]
        if chunk_key is None:
            return

        records = []
        if os.path.exists(self.tmp_path):
            with open(self.tmp_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            os.remove(self.tmp_path)

        if records:
            file_exists = os.path.exists(self.csv_path)
            with open(
                self.csv_path, "a" if file_exists else "w", newline="", encoding="utf-8"
            ) as f:
                writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
                if not file_exists:
                    writer.writeheader()
                writer.writerows(records)
            self.state["total_saved"] += len(records)

        conf_in_chunk = self.state.pop("conf_saved_in_chunk", 0)
        if conf_in_chunk > 0:
            self.state["conf_count"] = conf_in_chunk

        self.state["chunks_done"].append(chunk_key)
        self.state["chunk_in_progress"] = None
        self.state["pages_done"] = []
        self._save()


# ---------------------------------------------------------------------------
# IntegrityReport
# ---------------------------------------------------------------------------

@dataclass
class EstadoReport:
    estado_id: str
    estado_nombre: str
    expected: int
    retrieved: int
    failed_pages: list[int]
    truncation_detected: bool

    @property
    def missing(self) -> int:
        return max(0, self.expected - self.retrieved)

    @property
    def pct_complete(self) -> float:
        if self.expected == 0:
            return 100.0
        return (self.retrieved / self.expected) * 100

    @property
    def is_healthy(self) -> bool:
        return self.pct_complete >= 99.0 and not self.failed_pages and not self.truncation_detected

    def print(self):
        pct = self.pct_complete
        status = "\u2713" if pct >= 99.0 else ("\u26a0" if pct >= 95.0 else "\u2717")

        flags = []
        if self.failed_pages:
            flags.append(f"PAGS FALLIDAS: {self.failed_pages}")
        if self.truncation_detected:
            flags.append("TRUNCAMIENTO")
        flag_str = f"  | {' '.join(flags)}" if flags else ""

        print(
            f"  {self.estado_id:>2} {self.estado_nombre:<25}"
            f" Esperado: {self.expected:>6} | Recuperado: {self.retrieved:>6} |"
            f" Faltan: {self.missing:>5} ({pct:.1f}%) {status}{flag_str}"
        )


# ---------------------------------------------------------------------------
# Scrape de un chunk individual
# ---------------------------------------------------------------------------

async def scrape_chunk(
    api: TokenManager,
    estado_id: str,
    estado_nombre: str,
    chunk: Chunk,
    ckpt: CheckpointManager,
    rows_per_page: int = DEFAULT_ROWS_PER_PAGE,
    is_first_chunk: bool = False,
) -> int:
    """Pagina un rango de fechas y guarda los registros incrementalmente."""
    chunk_key = chunk.key

    if ckpt.is_chunk_done(chunk_key):
        return 0

    ckpt.ensure_chunk_started(chunk_key)

    filtros = build_filtros(
        estado_id=estado_id,
        fecha_inicio=chunk.fecha_inicio,
        fecha_fin=chunk.fecha_fin,
    )

    total_pages = math.ceil(chunk.expected_count / rows_per_page)
    validator = PageValidator(rows_per_page) if is_first_chunk else None
    pages_done = ckpt.get_pages_done()
    records_scraped = 0

    for page in range(1, total_pages + 1):
        if page in pages_done:
            continue

        try:
            data = await fetch_page_with_retry(api, filtros, page, rows_per_page)
            records = parse_search_response(data)

            if not is_first_chunk:
                records = [r for r in records if r["nombre"] != "CONFIDENCIAL"]

            is_last = page == total_pages
            if validator:
                validator.validate(page, len(records), is_last)

            ckpt.save_page(page, records)
            records_scraped += len(records)

        except Exception:
            ckpt.mark_page_failed(page)

        if page < total_pages:
            await asyncio.sleep(DELAY_BETWEEN_PAGES)

    if validator and validator.truncation_detected:
        ckpt.mark_truncation()

    ckpt.finish_chunk()
    return records_scraped


# ---------------------------------------------------------------------------
# scrape_estado (orquestador principal)
# ---------------------------------------------------------------------------

async def scrape_estado(
    estado_id: str,
    estado_nombre: str,
    fecha_inicio: str = "1900-01-01",
    fecha_fin: str | None = None,
    chunk_limit: int = DEFAULT_CHUNK_LIMIT,
    rows_per_page: int = DEFAULT_ROWS_PER_PAGE,
    output_dir: str = "data",
    force: bool = False,
) -> EstadoReport:
    """
    Scraping robusto de un estado completo.

    Args:
        estado_id: ID numerico del estado
        estado_nombre: Nombre para logging
        fecha_inicio: Fecha de inicio (default: 1900-01-01)
        fecha_fin: Fecha de fin (default: hoy)
        chunk_limit: Max registros por chunk antes de dividir
        rows_per_page: Registros por pagina
        output_dir: Directorio de salida
        force: Forzar re-scrapeo aunque el checkpoint indique completado

    Returns:
        EstadoReport con el resultado de integridad
    """
    if fecha_fin is None:
        fecha_fin = datetime.now().strftime("%Y-%m-%d")

    ckpt = CheckpointManager(estado_id, output_dir)

    if ckpt.is_complete() and not force:
        print(
            f"  {estado_id:>2} {estado_nombre:<25}"
            f" YA COMPLETO: {ckpt.state['total_saved']} registros"
        )
        return EstadoReport(
            estado_id=estado_id,
            estado_nombre=estado_nombre,
            expected=ckpt.state["total_expected"],
            retrieved=ckpt.state["total_saved"],
            failed_pages=[],
            truncation_detected=False,
        )

    if force or not ckpt.state["chunks_done"]:
        ckpt.clean()

    async with ConsultaAPIHttpx() as raw_api:
        api = TokenManager(raw_api)
        await api.ensure_token()

        filtros_full = build_filtros(
            estado_id=estado_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
        )
        total_full = await api.get_count(filtros_full)

        if total_full == 0:
            print(f"  {estado_id:>2} {estado_nombre:<25} 0 registros")
            return EstadoReport(
                estado_id=estado_id,
                estado_nombre=estado_nombre,
                expected=0,
                retrieved=0,
                failed_pages=[],
                truncation_detected=False,
            )

        ckpt.set_expected(total_full)

        first_year = await find_first_year_with_data(api, estado_id, fecha_fin, total_full)

        if first_year is None:
            return EstadoReport(
                estado_id=estado_id,
                estado_nombre=estado_nombre,
                expected=0,
                retrieved=0,
                failed_pages=[],
                truncation_detected=False,
            )

        effective_fi = f"{first_year}-01-01"
        chunks = await build_chunks(api, estado_id, effective_fi, fecha_fin, chunk_limit)

        n_chunks = len(chunks)
        print(
            f"  {estado_id:>2} {estado_nombre:<25}"
            f" {total_full:>6} regs  "
            f"({n_chunks} {'chunks' if n_chunks > 1 else 'chunk'} desde {first_year})",
            end="",
            flush=True,
        )

        for i, chunk in enumerate(chunks):
            is_first = (i == 0)
            await scrape_chunk(api, estado_id, estado_nombre, chunk, ckpt, rows_per_page,
                               is_first_chunk=is_first)

        print(f" \u2713 ({ckpt.state['total_saved']})")

        return EstadoReport(
            estado_id=estado_id,
            estado_nombre=estado_nombre,
            expected=total_full,
            retrieved=ckpt.state["total_saved"],
            failed_pages=ckpt.state["failed_pages"],
            truncation_detected=ckpt.state.get("truncation_detected", False),
        )
