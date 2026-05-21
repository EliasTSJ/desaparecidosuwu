#!/usr/bin/env python3
"""
Scrapeo nacional ASINCRONO de personas desaparecidas.
4 concurrentes × 1000 rows/pag + session.refresh() cada 3 paginas.
Rango: 1900-01-01 a hoy. Sin chunks. Retry con backoff.
"""
import asyncio, math, os, time, glob, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.api_httpx import ConsultaAPIHttpx
from scraper.parser import parse_search_response
from scraper.pipeline import build_filtros
from scraper.estados import ESTADOS

import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

FECHA_INICIO = "1900-01-01"
FECHA_FIN = "2026-05-31"
DATA_DIR = "data"
GRAFICAS_DIR = f"{DATA_DIR}/graficas"
ROWS_PER_PAGE = 1000
CSV_NACIONAL = f"{DATA_DIR}/mexico_full.csv"
SEM_LIMIT = 4
MAX_RETRIES = 3
RETRY_DELAY = 5
REFRESH_EVERY = 3

os.makedirs(GRAFICAS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

_sem = asyncio.Semaphore(SEM_LIMIT)


async def _retry_call(fn, name, sleep_before=0):
    for attempt in range(MAX_RETRIES + 1):
        try:
            if sleep_before and attempt > 0:
                await asyncio.sleep(sleep_before)
            return await fn()
        except Exception as e:
            msg = str(e)
            if attempt < MAX_RETRIES and any(k in msg.lower() for k in ("timeout", "dial", "econn", "refused", "reset")):
                wait = RETRY_DELAY * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            if attempt == MAX_RETRIES:
                raise
            raise


CHUNK_LIMIT = 5000

async def _scrape_range(estado_id, estado_nombre, fi, ff, label):
    """Scrapea un rango de fechas y devuelve los registros."""
    records = []
    async with ConsultaAPIHttpx() as api:
        try:
            await _retry_call(api.get_token, f"{label}/token")
        except Exception as e:
            print(f"    [{label}] ERROR token: {e}")
            return records

        filtros = build_filtros(estado_id=estado_id, fecha_inicio=fi, fecha_fin=ff)
        try:
            total = await _retry_call(lambda: api.get_count(filtros), f"{label}/count")
        except Exception as e:
            print(f"    [{label}] ERROR count: {e}")
            return records

        if not isinstance(total, int) or total == 0:
            return records

        total_pages = math.ceil(total / ROWS_PER_PAGE)
        for page in range(1, total_pages + 1):
            def _mk(p):
                return lambda: api.search_page(filtros, rows=ROWS_PER_PAGE, page=p)
            try:
                data = await _retry_call(_mk(page), f"{label}/pag_{page}")
                if isinstance(data, dict) and "data" in data:
                    records.extend(parse_search_response(data))
                else:
                    print(f"\n    [{label}] pag {page}: bad type")
            except Exception as e:
                print(f"\n    [{label}] pag {page}: {e}")
                continue
            if page < total_pages:
                await asyncio.sleep(0.3)
    return records


async def scrape_estado(estado_id: str, estado_nombre: str) -> list[dict]:
    csv_path = f"{DATA_DIR}/estado_{estado_id}.csv"
    if os.path.exists(csv_path):
        try:
            existing = pl.read_csv(csv_path, ignore_errors=True)
            n = existing.height
            print(f"  {estado_id:>2} {estado_nombre:<25} YA GUARDADO: {n}")
            return existing.to_dicts()
        except Exception:
            pass

    async with _sem:
        # 1. CONTAR rango completo
        async with ConsultaAPIHttpx() as api:
            await _retry_call(api.get_token, f"{estado_nombre}/token")
            filtros_full = build_filtros(estado_id=estado_id, fecha_inicio=FECHA_INICIO, fecha_fin=FECHA_FIN)
            total = await _retry_call(lambda: api.get_count(filtros_full), f"{estado_nombre}/count")

        if not isinstance(total, int) or total == 0:
            print(f"  {estado_id:>2} {estado_nombre:<25} 0 registros")
            return []

        if total <= CHUNK_LIMIT:
            print(f"  {estado_id:>2} {estado_nombre:<25} {total:>6} regs  (directo)", end="", flush=True)
            records = await _scrape_range(estado_id, estado_nombre, FECHA_INICIO, FECHA_FIN, estado_nombre)
        else:
            n_chunks = math.ceil(total / CHUNK_LIMIT)
            year_span = 126  # 2026 - 1900
            years_per_chunk = max(1, year_span // n_chunks)
            print(f"  {estado_id:>2} {estado_nombre:<25} {total:>6} regs  {n_chunks} chunks", end="", flush=True)

            records = []
            for i in range(n_chunks):
                cy = 1900 + i * years_per_chunk
                ny = min(2026, cy + years_per_chunk - 1) if i < n_chunks - 1 else 2026
                fi = f"{cy:04d}-01-01"
                ff = f"{ny:04d}-12-31"
                label = f"{estado_nombre} [{cy}-{ny}]"
                recs = await _scrape_range(estado_id, estado_nombre, fi, ff, label)
                records.extend(recs)

        if records:
            pl.DataFrame(records).write_csv(csv_path)
        print(f" ✓ ({len(records)})")
        return records


async def main_scrape():
    print("=" * 60)
    print(f"SCRAPING: {SEM_LIMIT} concurrentes × {ROWS_PER_PAGE} rows/pag (httpx)")
    print(f"Rango: {FECHA_INICIO} a {FECHA_FIN}")
    print("=" * 60)

    t_start = time.time()

    tasks = []
    for estado_id, estado_nombre in sorted(ESTADOS.items(), key=lambda x: int(x[0])):
        if estado_id == "33":
            continue
        tasks.append(scrape_estado(estado_id, estado_nombre))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_records = []
    for r in results:
        if isinstance(r, list):
            all_records.extend(r)
        elif isinstance(r, Exception):
            print(f"  FATAL: {r}")

    elapsed = time.time() - t_start
    print(f"\nTotal: {len(all_records)} registros en {elapsed:.0f}s ({elapsed/60:.1f} min)")

    if not all_records:
        print("ERROR: No hay datos.")
        return []

    return all_records


# ─── MAIN ───
all_records = asyncio.run(main_scrape())

if not all_records:
    exit(1)

# ─── CONSOLIDAR ───
print("\n" + "=" * 60)
print("CONSOLIDANDO...")
print("=" * 60)

all_dfs = []
for csv_file in sorted(glob.glob(f"{DATA_DIR}/estado_*.csv")):
    estado_id = csv_file.split("_")[-1].replace(".csv", "")
    if estado_id in ESTADOS:
        try:
            df = pl.read_csv(csv_file, ignore_errors=True)
        except Exception:
            df = pl.read_csv(csv_file, infer_schema_length=0)
        df = df.with_columns(pl.all().cast(pl.Utf8))
        print(f"  {estado_id:>2} {ESTADOS[estado_id]:<25} {df.height:>6}")
        all_dfs.append(df)

if not all_dfs:
    print("ERROR: Sin CSVs.")
    exit(1)

df = pl.concat(all_dfs)
print(f"\nTotal consolidado: {df.height}")

# ─── POLARS ───
print("\n" + "=" * 60)
print("ANALISIS POLARS")
print("=" * 60)

publicos = df.filter(pl.col("nombre") != "CONFIDENCIAL")
confidenciales = df.filter(pl.col("nombre") == "CONFIDENCIAL")
print(f"Publicos: {publicos.height} | Confidenciales: {confidenciales.height}")

publicos = publicos.with_columns(
    pl.col("fecha_hechos").str.strptime(pl.Date, "%d/%m/%Y", strict=False).alias("fecha"),
    pl.col("edad_actual").cast(pl.Int64, strict=False).alias("edad"),
)
publicos = publicos.with_columns(
    pl.col("fecha").dt.year().alias("anio"),
    pl.col("fecha").dt.month().alias("mes"),
    pl.col("sexo").str.to_uppercase().alias("sexo_norm"),
)
publicos.write_csv(CSV_NACIONAL)
print(f"CSV: {CSV_NACIONAL} ({os.path.getsize(CSV_NACIONAL):,} bytes)")

# ─── GRAFICAS ───
print("\n" + "=" * 60)
print("GRAFICAS")
print("=" * 60)

# 1 — Top 15 estados
print("[1/6] Estados...")
estado_counts = publicos.group_by("estado").len().sort("len", descending=True).head(15)
fig1 = px.bar(estado_counts, x="len", y="estado", orientation="h",
              title="Top 15 estados", labels={"len": "Casos", "estado": ""},
              text="len", color="len", color_continuous_scale="Reds")
fig1.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
fig1.write_html(f"{GRAFICAS_DIR}/01_estados_full.html")

# 2 — Por año (desde 2000)
print("[2/6] Tendencia...")
yearly = publicos.group_by("anio").len().sort("anio").filter(pl.col("anio") >= 2000)
fig2 = px.line(yearly, x="anio", y="len", markers=True,
               title="Desapariciones por año (desde 2000)", labels={"anio": "Año", "len": "Casos"})
fig2.update_layout(height=400, hovermode="x unified")
fig2.write_html(f"{GRAFICAS_DIR}/02_por_anio.html")

# 3 — Edades
print("[3/6] Edades...")
edades = publicos.filter(pl.col("edad").is_not_null() & (pl.col("edad") > 0) & (pl.col("edad") < 110))
fig3 = px.histogram(edades, x="edad", nbins=35, title="Edad", labels={"edad": "Edad"})
fig3.update_layout(height=400)
fig3.write_html(f"{GRAFICAS_DIR}/03_edades_full.html")

# 4 — Sexo
print("[4/6] Sexo...")
sexo_data = publicos.group_by("sexo_norm").len().filter(pl.col("sexo_norm").is_in(["HOMBRE", "MUJER"]))
fig4 = px.pie(sexo_data, values="len", names="sexo_norm", title="Por sexo")
fig4.update_traces(textinfo="label+percent+value")
fig4.update_layout(height=400)
fig4.write_html(f"{GRAFICAS_DIR}/04_sexo_full.html")

# 5 — Estatus
print("[5/6] Estatus...")
estatus_data = publicos.group_by("estatus").len().sort("len", descending=True)
fig5 = px.bar(estatus_data, x="estatus", y="len", title="Estatus", labels={"len": "Casos"}, text="len", color="estatus")
fig5.update_layout(height=400)
fig5.write_html(f"{GRAFICAS_DIR}/05_estatus_full.html")

# 6 — Top 15 municipios
print("[6/6] Municipios...")
muni_data = (
    publicos.with_columns(pl.concat_str([pl.col("municipio"), pl.lit(", "), pl.col("estado")]).alias("muni_estado"))
    .group_by("muni_estado").len().sort("len", descending=True).head(15)
)
fig6 = px.bar(muni_data, x="len", y="muni_estado", orientation="h",
              title="Top 15 municipios", labels={"len": "Casos", "muni_estado": ""}, text="len")
fig6.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
fig6.write_html(f"{GRAFICAS_DIR}/06_municipios_full.html")

# ─── DASHBOARD ───
print("\n[Dashboard]...")
dashboard = make_subplots(
    rows=3, cols=2,
    subplot_titles=["Top 15 estados", "Tendencia por año", "Edades", "Sexo", "Estatus", "Top 15 municipios"],
    specs=[[{"type": "bar"}, {"type": "scatter"}], [{"type": "histogram"}, {"type": "pie"}], [{"type": "bar"}, {"type": "bar"}]],
    vertical_spacing=0.1, horizontal_spacing=0.1,
)
for t in fig1.data: dashboard.add_trace(t, row=1, col=1)
for t in fig2.data: dashboard.add_trace(t, row=1, col=2)
for t in fig3.data: dashboard.add_trace(t, row=2, col=1)
for t in fig4.data: dashboard.add_trace(t, row=2, col=2)
for t in fig5.data: dashboard.add_trace(t, row=3, col=1)
for t in fig6.data: dashboard.add_trace(t, row=3, col=2)
dashboard.update_layout(height=1400, title_text=f"Dashboard nacional ({FECHA_INICIO} a {FECHA_FIN})", showlegend=False)
dashboard.write_html(f"{GRAFICAS_DIR}/dashboard_mexico_full.html")

# ─── RESUMEN ───
print()
print("=" * 60)
print("RESUMEN")
print("=" * 60)
print(f"Total:                   {df.height}")
print(f"Publicos:                {publicos.height}")
print(f"Confidenciales:          {confidenciales.height}")
print(f"H / M:                   {(publicos['sexo_norm']=='HOMBRE').sum()} / {(publicos['sexo_norm']=='MUJER').sum()}")
print(f"Edad promedio:           {publicos['edad'].mean():.1f}")
print(f"Edad mediana:            {publicos['edad'].median():.0f}")
print()
for row in estado_counts.head(5).iter_rows():
    print(f"  {row[1]:>6} casos — {row[0]}")
print(f"\nDashboard: {GRAFICAS_DIR}/dashboard_mexico_full.html")
