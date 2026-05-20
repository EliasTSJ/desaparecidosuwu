# Copyright 2026 Marimo. All rights reserved.
# /// script
# marimo-version = "0.23"
# requires-python = ">=3.10"
# dependencies = [
#     "marimo>=0.23",
#     "httpcloak>=1.6",
#     "pycryptodome>=3.20",
#     "pandas>=2.0",
#     "tqdm==4.67.3",
# ]
# ///

import marimo

__generated_with = "0.23.6"
app = marimo.App()


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # 🔍 Scraper RNPDNO
    "
        "## Registro Nacional de Personas Desaparecidas y No Localizadas

    "
        "Selecciona los filtros y presiona **Buscar** para obtener los registros de "
        "`consultapublicarnpdno.segob.gob.mx`.
    """)
    return


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import time, math
    from datetime import datetime, date

    return date, datetime, math, mo, pd, time


@app.cell
def _():
    from scraper.api import ConsultaAPI
    from scraper.parser import parse_search_response, save_csv
    from scraper.estados import ESTADOS
    from scraper.pipeline import build_filtros

    return ConsultaAPI, ESTADOS, build_filtros, parse_search_response, save_csv


@app.cell
def _(ConsultaAPI):
    api_session = ConsultaAPI(preset="chrome-latest")
    return (api_session,)


@app.cell(hide_code=True)
def _(mo):
    mo.md("## Filtros de búsqueda").callout(kind="info")
    return


@app.cell
def _(ESTADOS, mo):
    _opciones = {v: k for k, v in sorted(ESTADOS.items()) if k != "33"}
    estado = mo.ui.dropdown(
        options=_opciones, label="Estado", value=None, full_width=True,
    )
    estado
    return (estado,)


@app.cell
def _(mo):
    get_munis_state, set_munis_state = mo.state([])
    get_opts_state, set_opts_state = mo.state({"(selecciona un estado primero)": "none"})
    get_log_state, set_log_state = mo.state(["inicio"])
    return (
        get_log_state,
        get_munis_state,
        get_opts_state,
        set_log_state,
        set_munis_state,
        set_opts_state,
    )


@app.cell
def _(api_session, estado, set_log_state, set_munis_state, set_opts_state):
    _eid = estado.value or ""
    _log = [f"estado.value = {repr(_eid)}"]
    _munis = []
    _opts = {"(selecciona un estado primero)": "none"}

    if _eid:
        try:
            _log.append("obteniendo token...")
            api_session.get_token()
            _log.append("token OK")

            _log.append(f"get_municipios({_eid})...")
            _munis = api_session.get_municipios(_eid)
            _log.append(f"API: {len(_munis)} municipios")

            _opts = {"TODOS": ""}
            for m in _munis:
                _opts[m["municipio"]] = str(m["id"])
            _log.append(f"_opts listo: {len(_opts)} keys")
        except Exception as _err:
            _log.append(f"ERROR: {_err}")
            _opts = {"(error al cargar)": str(_err)[:60]}
            _munis = []
    else:
        _log.append("sin estado")

    _log.append(f"FIN | munis={len(_munis)} | opts={len(_opts)}")
    set_munis_state(_munis)
    set_opts_state(_opts)
    set_log_state(_log)
    return


@app.cell
def _(get_log_state, get_munis_state, get_opts_state, mo):
    _opts = get_opts_state()
    _munis = get_munis_state()
    _log = get_log_state()

    municipio = mo.ui.dropdown(
        options=_opts,
        label="Municipio o Alcaldía",
        value=list(_opts.keys())[0] if _opts else None,
        full_width=True,
    )

    _confirmacion = (
        mo.md(
            f"**{len(_munis)}** municipios: "
            + ", ".join(m["municipio"] for m in _munis[:5])
            + (" ..." if len(_munis) > 5 else "")
        )
        if _munis
        else mo.md("")
    )

    _log_text = mo.accordion(
        {"🔍 Log de depuracion": mo.md("  \n".join(_log))}
    ) if _log else mo.md("")

    mo.vstack([municipio, _confirmacion, _log_text])
    return (municipio,)


@app.cell
def _(date, mo):
    fechas = mo.ui.date_range(
        start=date(2015, 1, 1), stop=date.today(),
        label="Rango de fechas de hechos", full_width=True,
    )
    fechas
    return (fechas,)


@app.cell
def _(mo):
    folio = mo.ui.text(
        label="Folio o nombre (mín. 5 caracteres, opcional)",
        full_width=True,
    )
    folio
    return (folio,)


@app.cell
def _(mo):
    rows = mo.ui.slider(
        start=10, stop=200, step=10, value=50,
        label="Registros por página", show_value=True,
    )
    rows
    return (rows,)


@app.cell
def _(mo):
    max_pages = mo.ui.number(
        start=0, stop=1000, value=0,
        label="Máx. páginas (0 = todas)",
    )
    max_pages
    return (max_pages,)


@app.cell
def _(mo):
    buscar = mo.ui.run_button(label="🔍 Buscar", kind="success")
    buscar
    return (buscar,)


@app.cell
def _(mo):
    get_msg_state, set_msg_state = mo.state(["👆 Selecciona filtros y presiona **Buscar**"])
    get_resultados_state, set_resultados_state = mo.state([])
    return get_msg_state, get_resultados_state, set_msg_state, set_resultados_state


@app.cell
def _(
    api_session,
    build_filtros,
    buscar,
    estado,
    fechas,
    folio,
    math,
    max_pages,
    mo,
    municipio,
    parse_search_response,
    rows,
    set_msg_state,
    set_resultados_state,
    time,
):
    estado_val = estado.value or ""
    resultados = []
    _mensajes = ["👆 Selecciona filtros y presiona **Buscar**"]

    if buscar.value:
        _fi = fechas.value[0].strftime("%Y-%m-%d") if fechas.value and fechas.value[0] else ""
        _ff = fechas.value[1].strftime("%Y-%m-%d") if fechas.value and fechas.value[1] else ""

        _filtros = build_filtros(
            estado_id=estado_val,
            municipio_id=municipio.value or "",
            fecha_inicio=_fi, fecha_fin=_ff,
            folio=folio.value or "",
        )

        api_session.get_token()

        _mensajes = ["📊 **Contando registros...**"]
        total_encontrado = api_session.get_count(_filtros)

        if total_encontrado == 0:
            _mensajes.append("⚠️ No se encontraron registros.")
        else:
            _r = rows.value or 50
            _mp = max_pages.value or 0
            _pags = math.ceil(total_encontrado / _r)
            if _mp and _mp < _pags:
                _pags = _mp

            _mensajes.append(
                f"Registros: **{total_encontrado}** | Páginas: **{_pags}**"
            )

            with mo.status.progress_bar(total=_pags) as _bar:
                for _page in range(1, _pags + 1):
                    try:
                        _data = api_session.search_page(_filtros, rows=_r, page=_page)
                        resultados.extend(parse_search_response(_data))
                    except Exception as e:
                        _mensajes.append(f"❌ Error pág {_page}: {e}")
                        continue
                    _bar.update()
                    if _page < _pags:
                        time.sleep(0.5)

            _mensajes.append(f"### ✅ {len(resultados)} registros")

        set_msg_state(list(_mensajes))
        set_resultados_state(list(resultados))

    return estado_val


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Resultados
    """)
    return


@app.cell(hide_code=True)
def _(get_msg_state, mo):
    _mensajes = get_msg_state()
    mo.md("  \n".join(f"- {m}" for m in _mensajes))
    return


@app.cell
def _(get_resultados_state, mo, pd):
    _res = get_resultados_state()

    if not _res:
        _output = mo.md("Sin resultados. Ejecuta una búsqueda.")
    else:
        _df = pd.DataFrame(_res)
        _cols = [
            'nombre_completo', 'sexo', 'edad_actual', 'fecha_hechos',
            'estado', 'municipio', 'estatus', 'dependencia_origen',
        ]
        _cols = [c for c in _cols if c in _df.columns]
        _df_show = _df[_cols].head(100)

        _md = f"### Resultados ({len(_res)} registros)\n\n"
        _md += _df_show.to_markdown(index=False)
        _md += f"\n\n*Mostrando {min(len(_res), 100)} de {len(_res)} registros.*"
        _output = mo.md(_md)

    return _output


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Exportar CSV
    """)
    return


@app.cell
def _(datetime, estado_val, get_resultados_state, mo, save_csv):
    _res = get_resultados_state()

    if not _res:
        _output = mo.md("")
    else:
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _nombre = estado_val.replace(" ", "_").lower() if estado_val else "todos"
        _path = f"data/resultados_{_nombre}_{_ts}.csv"
        save_csv(_res, _path)
        _output = mo.md(
            f"📥 **{len(_res)}** registros exportados a: `{_path}`\n\n"
            f"El archivo está en la carpeta `data/` del proyecto."
        )

    return _output


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Notas
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    | Concepto | Detalle |
    "
        "|----------|---------|
    "
        "| **CONFIDENCIAL** | Protegidos por ley |
    "
        "| Fuente | `consultapublicarnpdno.segob.gob.mx` |
    "
        "| Fingerprint | `httpcloak` emula Chrome (JA3/JA4) |
    "
        "| Reactividad | Cambiar filtros actualiza automáticamente |
    "
        "| Ejecutar app | `marimo run scraper_notebook.py` |
    "
        "| Ejecutar script | `python scraper_notebook.py` |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        "### Cómo usar\n\n"
        "1. **Selecciona un estado** → los municipios se cargan automáticamente\n"
        "2. **Opcional**: municipio, fechas, folio\n"
        "3. **Presiona Buscar** → barra de progreso\n"
        "4. **Explora** la tabla de resultados\n"
        "5. **Exporta** a CSV con un clic"
    ).callout(kind="tip")
    return


if __name__ == "__main__":
    app.run()
