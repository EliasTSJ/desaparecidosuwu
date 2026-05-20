"""
Estados de Mexico con sus IDs (hardcodeados en el frontend).
"""

ESTADOS: dict[str, str] = {
    "1": "Aguascalientes",
    "2": "Baja California",
    "3": "Baja California Sur",
    "4": "Campeche",
    "5": "Coahuila",
    "6": "Colima",
    "7": "Chiapas",
    "8": "Chihuahua",
    "9": "Ciudad de Mexico",
    "10": "Durango",
    "11": "Guanajuato",
    "12": "Guerrero",
    "13": "Hidalgo",
    "14": "Jalisco",
    "15": "Estado de Mexico",
    "16": "Michoacan",
    "17": "Morelos",
    "18": "Nayarit",
    "19": "Nuevo Leon",
    "20": "Oaxaca",
    "21": "Puebla",
    "22": "Queretaro",
    "23": "Quintana Roo",
    "24": "San Luis Potosi",
    "25": "Sinaloa",
    "26": "Sonora",
    "27": "Tabasco",
    "28": "Tamaulipas",
    "29": "Tlaxcala",
    "30": "Veracruz",
    "31": "Yucatan",
    "32": "Zacatecas",
    "33": "Se Desconoce",
}

# Mapa inverso: nombre del estado → ID
ESTADO_ID_MAP = {v.lower(): k for k, v in ESTADOS.items()}
# Tambien aceptar los nombres con acentos como aparecen en el frontend
ESTADO_ID_MAP["ciudad de méxico"] = "9"
ESTADO_ID_MAP["méxico"] = "15"
ESTADO_ID_MAP["michoacán"] = "16"
ESTADO_ID_MAP["nuevo león"] = "19"
ESTADO_ID_MAP["san luis potosí"] = "24"
ESTADO_ID_MAP["yucatán"] = "31"
