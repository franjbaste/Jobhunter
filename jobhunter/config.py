"""Personaliza el monitor aquí. No guardes tokens de Telegram en este archivo."""
from pathlib import Path

# MISMO archivo que utiliza IBM_monitor3.py si extraes este proyecto en
# ~/Main/Jobhunter. No borres ni reemplaces jobhunter.db.
BASE_DATOS = Path(__file__).resolve().parents[1] / "jobhunter.db"

# Opciones de IBM conservadas del programa original.
URL_BUSCADOR = "https://www.ibm.com/careers/search"
MOSTRAR_NAVEGADOR = False
SEGUNDOS_ENTRE_PAGINAS = 3
INTENTOS_POR_PAGINA = 2
TIMEOUT_MS = 30_000

# Alertas: NO afecta a qué ofertas se almacenan en SQLite.
SOLO_JUNIOR_Y_PRACTICAS = True
REVISAR_MULTICIUDAD = True
MAX_AVISOS_INDIVIDUALES = 10  # por empresa y ejecución

# Activa empresas Greenhouse indicando el token real de su job board.
# Ejemplo de formato (descomenta y sustituye por tokens REALES):
# GREENHOUSE_EMPRESAS = {"Empresa X": "token-de-su-job-board"}
GREENHOUSE_EMPRESAS: dict[str, str] = {}
