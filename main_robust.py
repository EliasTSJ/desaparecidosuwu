#!/usr/bin/env python3
"""
Scraper nacional robusto de personas desaparecidas.
4 concurrentes x 1000 rows/pag. Rango: 1900-01-01 a fecha de hoy.
Con checkpointing, retry, validacion de integridad y graficas.
"""
import asyncio
import glob
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.robust_pipeline import scrape_estado
from scraper.estados import ESTADOS

import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

FECHA_INICIO = "1900-01-01"
FECHA_FIN = datetime.now().strftime("%Y-%m-%d")
DATA_DIR = "data"
GRAFICAS_DIR = f"{DATA_DIR}/graficas"
ROWS_PER_PAGE = 1000
CSV_NACIONAL = f"{DATA_DIR}/mexico_full.csv"
SEM_LIMIT = 4

os.makedirs(GRAFICAS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

_sem = asyncio.Semaphore(SEM_LIMIT)

STATE_RETRIES = 2


async def scrape_one(estado_id: str, estado_nombre: str):
    async with _sem:
        last_error = None
        for attempt in range(STATE_RETRIES + 1):
            try:
                return await scrape_estado(
                    estado_id=estado_id,
                    estado_nombre=estado_nombre,
                    fecha_inicio=FECHA_INICIO,
                    fecha_fin=FECHA_FIN,
                    rows_per_page=ROWS_PER_PAGE,
                    output_dir=DATA_DIR,
                )
            except Exception as e:
                last_error = e
                if attempt < STATE_RETRIES:
                    await asyncio.sleep(10 * (attempt + 1))
        raise last_error


async def main_scrape():
    print("=" * 60)
    print(f"SCRAPING ROBUSTO: {SEM_LIMIT} concurrentes x {ROWS_PER_PAGE} rows/pag")
    print(f"Rango: {FECHA_INICIO} a {FECHA_FIN}")
    print("=" * 60)

    t_start = time.time()

    tasks = []
    for estado_id, estado_nombre in sorted(ESTADOS.items(), key=lambda x: int(x[0])):
        tasks.append(scrape_one(estado_id, estado_nombre))

    reports = await asyncio.gather(*tasks, return_exceptions=True)

    print()
    print("=" * 60)
    print("RESUMEN DE INTEGRIDAD")
    print("=" * 60)

    total_expected = 0
    total_retrieved = 0
    total_failed = 0
    estados_con_error = 0

    for r in reports:
        if isinstance(r, Exception):
            print(f"  FATAL: {r}")
            estados_con_error += 1
            continue
        r.print()
        total_expected += r.expected
        total_retrieved += r.retrieved
        total_failed += len(r.failed_pages)
        if not r.is_healthy:
            estados_con_error += 1

    print("-" * 60)
    pct = (total_retrieved / total_expected * 100) if total_expected else 0
    print(
        f"  TOTAL:  Esperado {total_expected} | "
        f"Recuperado {total_retrieved} | "
        f"Pags fallidas {total_failed} | "
        f"Estados con error {estados_con_error} | "
        f"{pct:.1f}%"
    )

    elapsed = time.time() - t_start
    print(f"\nTiempo: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    return reports


def consolidar_csvs():
    print()
    print("=" * 60)
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
        print("ERROR: Sin CSVs para consolidar.")
        return None, None, None

    df = pl.concat(all_dfs)
    print(f"\nTotal consolidado: {df.height}")

    publicos = df.filter(pl.col("nombre") != "CONFIDENCIAL")
    confidenciales = df.filter(pl.col("nombre") == "CONFIDENCIAL")
    print(f"Publicos: {publicos.height} | Confidenciales: {confidenciales.height}")

    if publicos.height > 0:
        publicos = publicos.with_columns(
            pl.col("fecha_hechos")
            .str.strptime(pl.Date, "%d/%m/%Y", strict=False)
            .alias("fecha"),
            pl.col("edad_actual").cast(pl.Int64, strict=False).alias("edad"),
        )
        publicos = publicos.with_columns(
            pl.col("fecha").dt.year().alias("anio"),
            pl.col("fecha").dt.month().alias("mes"),
            pl.col("sexo").str.to_uppercase().alias("sexo_norm"),
        )
        publicos.write_csv(CSV_NACIONAL)
        print(f"CSV: {CSV_NACIONAL} ({os.path.getsize(CSV_NACIONAL):,} bytes)")

    return df, publicos, confidenciales


def generar_graficas(df_full: pl.DataFrame, publicos: pl.DataFrame):
    if publicos is None or publicos.height == 0:
        print("Sin datos publicos para graficar.")
        return

    print()
    print("=" * 60)
    print("GRAFICAS")
    print("=" * 60)

    # 1 — Top 15 estados
    print("[1/6] Estados...")
    estado_counts = (
        publicos.group_by("estado")
        .len()
        .sort("len", descending=True)
        .head(15)
    )
    fig1 = px.bar(
        estado_counts,
        x="len",
        y="estado",
        orientation="h",
        title=f"Top 15 estados ({FECHA_INICIO[:4]}-{FECHA_FIN[:4]})",
        labels={"len": "Casos", "estado": ""},
        text="len",
        color="len",
        color_continuous_scale="Reds",
    )
    fig1.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
    fig1.write_html(f"{GRAFICAS_DIR}/01_estados_full.html")

    # 2 — Tendencia anual (desde 2000)
    print("[2/6] Tendencia...")
    yearly = (
        publicos.group_by("anio")
        .len()
        .sort("anio")
        .filter(pl.col("anio") >= 2000)
    )
    fig2 = px.line(
        yearly,
        x="anio",
        y="len",
        markers=True,
        title="Desapariciones por anio (desde 2000)",
        labels={"anio": "Anio", "len": "Casos"},
    )
    fig2.update_layout(height=400, hovermode="x unified")
    fig2.write_html(f"{GRAFICAS_DIR}/02_por_anio.html")

    # 3 — Edades
    print("[3/6] Edades...")
    edades = publicos.filter(
        pl.col("edad").is_not_null()
        & (pl.col("edad") > 0)
        & (pl.col("edad") < 110)
    )
    if edades.height > 0:
        fig3 = px.histogram(
            edades, x="edad", nbins=35, title="Distribucion de edades",
            labels={"edad": "Edad"},
        )
        fig3.update_layout(height=400)
        fig3.write_html(f"{GRAFICAS_DIR}/03_edades_full.html")

    # 4 — Sexo
    print("[4/6] Sexo...")
    sexo_data = publicos.group_by("sexo_norm").len().filter(
        pl.col("sexo_norm").is_in(["HOMBRE", "MUJER"])
    )
    if sexo_data.height > 0:
        fig4 = px.pie(
            sexo_data, values="len", names="sexo_norm",
            title="Por sexo",
        )
        fig4.update_traces(textinfo="label+percent+value")
        fig4.update_layout(height=400)
        fig4.write_html(f"{GRAFICAS_DIR}/04_sexo_full.html")

    # 5 — Estatus
    print("[5/6] Estatus...")
    estatus_data = publicos.group_by("estatus").len().sort("len", descending=True)
    fig5 = px.bar(
        estatus_data, x="estatus", y="len", title="Estatus de las victimas",
        labels={"len": "Casos"}, text="len", color="estatus",
    )
    fig5.update_layout(height=400)
    fig5.write_html(f"{GRAFICAS_DIR}/05_estatus_full.html")

    # 6 — Top 15 municipios
    print("[6/6] Municipios...")
    muni_data = (
        publicos.with_columns(
            pl.concat_str(
                [pl.col("municipio"), pl.lit(", "), pl.col("estado")]
            ).alias("muni_estado")
        )
        .group_by("muni_estado")
        .len()
        .sort("len", descending=True)
        .head(15)
    )
    fig6 = px.bar(
        muni_data,
        x="len",
        y="muni_estado",
        orientation="h",
        title="Top 15 municipios",
        labels={"len": "Casos", "muni_estado": ""},
        text="len",
    )
    fig6.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
    fig6.write_html(f"{GRAFICAS_DIR}/06_municipios_full.html")

    # ─── DASHBOARD ───
    print("\n[Dashboard]...")
    dashboard = make_subplots(
        rows=3,
        cols=2,
        subplot_titles=[
            "Top 15 estados",
            "Tendencia por anio",
            "Distribucion de edades",
            "Por sexo",
            "Estatus",
            "Top 15 municipios",
        ],
        specs=[
            [{"type": "bar"}, {"type": "scatter"}],
            [{"type": "histogram"}, {"type": "pie"}],
            [{"type": "bar"}, {"type": "bar"}],
        ],
        vertical_spacing=0.1,
        horizontal_spacing=0.1,
    )
    for t in fig1.data:
        dashboard.add_trace(t, row=1, col=1)
    for t in fig2.data:
        dashboard.add_trace(t, row=1, col=2)
    for t in fig3.data:
        dashboard.add_trace(t, row=2, col=1)
    for t in fig4.data:
        dashboard.add_trace(t, row=2, col=2)
    for t in fig5.data:
        dashboard.add_trace(t, row=3, col=1)
    for t in fig6.data:
        dashboard.add_trace(t, row=3, col=2)

    dashboard.update_layout(
        height=1400,
        title_text=f"Dashboard Nacional RNPDNO ({FECHA_INICIO} a {FECHA_FIN})",
        showlegend=False,
    )
    dashboard.write_html(f"{GRAFICAS_DIR}/dashboard_mexico_full.html")

    # ─── RESUMEN ───
    print()
    print("=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    total_general = df_full.height if df_full is not None else 0
    confidenciales_count = total_general - publicos.height
    print(f"Total general:          {total_general}")
    print(f"Publicos:               {publicos.height}")
    print(f"Confidenciales:         {confidenciales_count}")

    if publicos.height > 0:
        h = publicos.filter(pl.col("sexo_norm") == "HOMBRE").height
        m = publicos.filter(pl.col("sexo_norm") == "MUJER").height
        edad_mean = publicos["edad"].mean()
        edad_median = publicos["edad"].median()
        print(f"Hombres / Mujeres:      {h} / {m}")
        print(f"Edad promedio:          {edad_mean:.1f}")
        print(f"Edad mediana:           {edad_median:.0f}")

    print()
    top5 = (
        publicos.group_by("estado")
        .len()
        .sort("len", descending=True)
        .head(5)
    )
    for row in top5.iter_rows():
        print(f"  {row[1]:>6} casos — {row[0]}")

    print(f"\nDashboard: {GRAFICAS_DIR}/dashboard_mexico_full.html")
    print(f"CSV nacional: {CSV_NACIONAL}")


# ─── EJECUCION ───
if __name__ == "__main__":
    reports = asyncio.run(main_scrape())
    df, publicos, confidenciales = consolidar_csvs()
    generar_graficas(df, publicos)
