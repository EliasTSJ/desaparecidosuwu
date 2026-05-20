# Scraper RNPDNO

Scraper del **Registro Nacional de Personas Desaparecidas y No Localizadas** (RNPDNO) de México.

Fuente oficial: `https://consultapublicarnpdno.segob.gob.mx/`

## Instalación

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Uso

### Notebook interactivo (Marimo)

```bash
source venv/bin/activate
marimo edit scraper_notebook.py   # modo edición
marimo run scraper_notebook.py    # modo app (solo outputs)
```

### CLI

```bash
python main.py --estado Tabasco
python main.py --estado-id 27 --fecha-inicio 01/01/2023 --fecha-fin 31/12/2023
python main.py --estado Tabasco --municipio 4
python main.py --all-estados --rows 100 --delay 0.5
```

## Filtros disponibles

| Filtro | Descripción |
|--------|------------|
| `--estado` | Nombre del estado (ej: Tabasco, Jalisco) |
| `--estado-id` | ID numérico del estado (ej: 27 para Tabasco) |
| `--municipio` | ID del municipio o alcaldía |
| `--fecha-inicio` | Fecha inicio (DD/MM/YYYY) |
| `--fecha-fin` | Fecha fin (DD/MM/YYYY) |
| `--folio` | Búsqueda por folio/nombre (mín. 5 caracteres) |
| `--rows` | Registros por página (default: 50) |
| `--max-pages` | Máximo de páginas (0 = todas) |
| `--delay` | Segundos entre requests (default: 1.0) |
| `--output` | Ruta base de salida |
| `--format` | csv o json |

## Estructura del proyecto

```
scraper/
  __init__.py
  api.py          # Cliente HTTP con httpcloak (fingerprint TLS Chrome)
  crypto.py       # Encriptación AES (CryptoJS ↔ Python)
  parser.py       # Parseo de respuestas + exportación CSV/JSON
  pipeline.py     # Orquestación del scraping
  estados.py      # Mapa de los 32 estados de México
scraper_notebook.py  # Notebook Marimo interactivo
main.py              # CLI del scraper
```

## Tecnología

- **httpcloak**: Fingerprint TLS JA3/JA4 de Chrome para evitar bloqueos
- **pycryptodome**: Encriptación AES que replica CryptoJS del frontend
- **marimo**: Notebook reactivo (celdas se re-ejecutan automáticamente)
- **pandas**: Manipulación y exportación de datos

## Nota

Los registros marcados como **CONFIDENCIAL** están protegidos por ley y no contienen datos personales visibles.
