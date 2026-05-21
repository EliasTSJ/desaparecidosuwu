#!/usr/bin/env python3
"""
Scrapeo nacional de personas desaparecidas (ultimos 12 meses).
Itera los 32 estados, consolida datos, genera graficas interactivas.
Polars para datos + Plotly para visualizacion.

RESILIENTE: guarda CSV parcial por estado, reanuda si se interrumpe.
"""
import sys, time, math, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.api import ConsultaAPI
from scraper.parser import parse_search_response
from scraper.pipeline import build_filtros
from scraper.estados import ESTADOS

import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ─── CONFIG ───
FECHA_INICIO = "2025-05-01"
FECHA_FIN = "2026-05-31"
DATA_DIR = "data"
GRAFICAS_DIR = f"{DATA_DIR}/graficas"
ROWS_PER_PAGE = 200  # mas rapido: 4x menos llamadas
CSV_NACIONAL = f"{DATA_DIR}/mexico_12m.csv"

os.makedirs(GRAFICAS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ─── FASE 1: SCRAPEAR ───
print("=" * 60)
print("SCRAPING NACIONAL: los 32 estados de Mexico (REANUDABLE)")
print(f"Rango: {FECHA_INICIO} a {FECHA_FIN}  |  Rows/pag: {ROWS_PER_PAGE}")
print("=" * 60)

for estado_id, estado_nombre in sorted(ESTADOS.items(), key=lambda x: int(x[0])):
    if estado_id == "33":
        continue

    csv_path = f"{DATA_DIR}/estado_{estado_id}.csv"
    if os.path.exists(csv_path):
        existing = pl.read_csv(csv_path)
        print(f"  {estado_id:>2} {estado_nombre:<25} YA GUARDADO: {existing.height} regs")
        continue

    api = ConsultaAPI(preset="chrome-latest")
    try:
        api.get_token()
    except Exception as e:
        print(f"  {estado_id:>2} {estado_nombre:<25} ERROR token: {e}")
        api.close()
        continue

    filtros = build_filtros(estado_id=estado_id, fecha_inicio=FECHA_INICIO, fecha_fin=FECHA_FIN)

    try:
        total = api.get_count(filtros)
    except Exception as e:
        print(f"  {estado_id:>2} {estado_nombre:<25} ERROR count: {e}")
        api.close()
        continue

    if not isinstance(total, int) or total == 0:
        print(f"  {estado_id:>2} {estado_nombre:<25} 0 registros")
        api.close()
        continue

    total_pages = math.ceil(total / ROWS_PER_PAGE)
    print(f"  {estado_id:>2} {estado_nombre:<25} {total:>6} regs  {total_pages:>3} pags ", end="", flush=True)

    records = []
    for page in range(1, total_pages + 1):
        try:
            data = api.search_page(filtros, rows=ROWS_PER_PAGE, page=page)
            parsed = parse_search_response(data)
            records.extend(parsed)
        except Exception as e:
            print(f"\n    ERROR pag {page}: {e}")
            continue
        if page < total_pages:
            time.sleep(0.2)

    api.close()

    # Guardar CSV parcial
    if records:
        pl.DataFrame(records).write_csv(csv_path)
        print(f"✓ ({len(records)})")
    else:
        print(f"✗ (0)")
    time.sleep(0.15)

# ─── FASE 2: CONSOLIDAR ───
print("\n" + "=" * 60)
print("CONSOLIDANDO CSVs...")
print("=" * 60)

all_dfs = []
for csv_file in sorted(glob.glob(f"{DATA_DIR}/estado_*.csv")):
    estado_id = csv_file.split("_")[-1].replace(".csv", "")
    if estado_id in ESTADOS:
        df = pl.read_csv(csv_file)
        print(f"  {estado_id:>2} {ESTADOS[estado_id]:<25} {df.height:>6} regs")
        all_dfs.append(df)

if not all_dfs:
    print("ERROR: No hay datos.")
    exit(1)

df = pl.concat(all_dfs)
print(f"\nTotal consolidado: {df.height} registros")
print(f"Columnas: {df.columns}")

# ─── FASE 3: POLARS ───
print("\n" + "=" * 60)
print("ANALISIS CON POLARS")
print("=" * 60)

publicos = df.filter(pl.col("nombre") != "CONFIDENCIAL")
confidenciales = df.filter(pl.col("nombre") == "CONFIDENCIAL")
print(f"Publicos: {publicos.height} | Confidenciales: {confidenciales.height}")

if publicos.height == 0:
    print("ERROR: No hay registros publicos.")
    exit(1)

publicos = publicos.with_columns(
    pl.col("fecha_hechos").str.strptime(pl.Date, "%d/%m/%Y", strict=False).alias("fecha"),
    pl.col("edad_actual").cast(pl.Int64, strict=False).alias("edad"),
)
publicos = publicos.with_columns(
    pl.col("fecha").dt.year().alias("anio"),
    pl.col("fecha").dt.month().alias("mes"),
    pl.col("sexo").str.to_uppercase().alias("sexo_norm"),
)

# Guardar CSV consolidado (solo publicos)
publicos.write_csv(CSV_NACIONAL)
print(f"CSV nacional: {CSV_NACIONAL} ({os.path.getsize(CSV_NACIONAL):,} bytes)")

# ─── FASE 4: GRAFICAS ───
print("\n" + "=" * 60)
print("GRAFICAS INTERACTIVAS")
print("=" * 60)

# 1 — Estados
print("[1/6] Estados...")
estado_counts = publicos.group_by("estado").len().sort("len", descending=True).head(15)
fig1 = px.bar(estado_counts, x="len", y="estado", orientation="h",
              title="Top 15 estados", labels={"len": "Casos", "estado": ""},
              text="len", color="len", color_continuous_scale="Reds")
fig1.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
fig1.write_html(f"{GRAFICAS_DIR}/01_estados.html")

# 2 — Mes
print("[2/6] Tendencia...")
monthly = (
    publicos.group_by(["anio", "mes"]).len().sort(["anio", "mes"])
    .with_columns(pl.concat_str([pl.col("anio").cast(pl.Utf8), pl.lit("-"), pl.col("mes").cast(pl.Utf8)]).alias("periodo"))
)
fig2 = px.line(monthly, x="periodo", y="len", markers=True,
               title="Desapariciones por mes", labels={"periodo": "Mes", "len": "Casos"})
fig2.update_layout(height=400, hovermode="x unified")
fig2.write_html(f"{GRAFICAS_DIR}/02_por_mes.html")

# 3 — Edades
print("[3/6] Edades...")
edades = publicos.filter(pl.col("edad").is_not_null() & (pl.col("edad") > 0) & (pl.col("edad") < 110))
fig3 = px.histogram(edades, x="edad", nbins=35, title="Edad de desaparecidos", labels={"edad": "Edad"})
fig3.update_layout(height=400)
fig3.write_html(f"{GRAFICAS_DIR}/03_edades.html")

# 4 — Sexo
print("[4/6] Sexo...")
sexo_data = publicos.group_by("sexo_norm").len().filter(pl.col("sexo_norm").is_in(["HOMBRE", "MUJER"]))
fig4 = px.pie(sexo_data, values="len", names="sexo_norm", title="Por sexo")
fig4.update_traces(textinfo="label+percent+value")
fig4.update_layout(height=400)
fig4.write_html(f"{GRAFICAS_DIR}/04_sexo.html")

# 5 — Estatus
print("[5/6] Estatus...")
estatus_data = publicos.group_by("estatus").len().sort("len", descending=True)
fig5 = px.bar(estatus_data, x="estatus", y="len", title="Estatus", labels={"len": "Casos", "estatus": "Estatus"}, text="len", color="estatus")
fig5.update_layout(height=400)
fig5.write_html(f"{GRAFICAS_DIR}/05_estatus.html")

# 6 — Municipios top 10
print("[6/6] Municipios...")
muni_data = (
    publicos.with_columns(pl.concat_str([pl.col("municipio"), pl.lit(", "), pl.col("estado")]).alias("muni_estado"))
    .group_by("muni_estado").len().sort("len", descending=True).head(10)
)
fig6 = px.bar(muni_data, x="len", y="muni_estado", orientation="h",
              title="Top 10 municipios", labels={"len": "Casos", "muni_estado": ""}, text="len")
fig6.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
fig6.write_html(f"{GRAFICAS_DIR}/06_municipios.html")

# ─── DASHBOARD ───
print("\n[Dashboard]...")
dashboard = make_subplots(
    rows=3, cols=2,
    subplot_titles=["Top 15 estados", "Tendencia por mes", "Distribucion de edades", "Por sexo", "Estatus", "Top 10 municipios"],
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
dashboard.write_html(f"{GRAFICAS_DIR}/dashboard_mexico.html")

# ─── RESUMEN ───
print()
print("=" * 60)
print("RESUMEN")
print("=" * 60)
print(f"Total registros:       {df.height}")
print(f"Publicos:               {publicos.height}")
print(f"Confidenciales:         {confidenciales.height}")
print(f"Estados:                {publicos['estado'].n_unique()}")
print(f"H / M:                  {(publicos['sexo_norm']=='HOMBRE').sum()} / {(publicos['sexo_norm']=='MUJER').sum()}")
print(f"Edad promedio:          {publicos['edad'].mean():.1f}")
print(f"Edad mediana:           {publicos['edad'].median():.0f}")
print()
for row in estado_counts.head(5).iter_rows():
    print(f"  {row[1]:>5} casos — {row[0]}")
print(f"\nDashboard: {GRAFICAS_DIR}/dashboard_mexico.html")
print(f"CSV: {CSV_NACIONAL}")
