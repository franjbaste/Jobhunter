"""Filtros COMUNES para decidir alertas (nunca para descartar del historial)."""
from __future__ import annotations
from jobhunter.config import SOLO_JUNIOR_Y_PRACTICAS, REVISAR_MULTICIUDAD
from jobhunter.models import Oferta

TIPOS_JUNIOR = {"internship", "entry level", "graduate", "apprenticeship"}
PALABRAS_JUNIOR = (
    "intern", "internship", "entry level", "graduate", "junior", "trainee",
    "apprentice", "placement", "co-op", "beca", "prácticas", "practicas",
)

# Europa geográfica (no solo la Unión Europea) y Estados Unidos.
CODIGOS_EUROPA = {
    "AL", "AD", "AT", "BE", "BA", "BG", "BY", "CH", "CY", "CZ",
    "DE", "DK", "EE", "ES", "FI", "FR", "GB", "UK", "GR", "HR",
    "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MC", "MD",
    "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "RU",
    "SE", "SI", "SK", "SM", "TR", "UA", "VA", "XK", "GI",
    "IM", "JE", "GG", "FO", "AX",
}
NOMBRES_EUROPA = {
    "albania", "andorra", "austria", "belgium", "belgica", "bosnia",
    "bulgaria", "belarus", "switzerland", "suiza", "cyprus", "chipre",
    "czech republic", "czechia", "denmark", "dinamarca", "estonia",
    "spain", "espana", "españa", "finland", "finlandia", "france",
    "francia", "united kingdom", "great britain", "england", "scotland",
    "wales", "greece", "croatia", "hungary", "ireland", "iceland",
    "italy", "italia", "liechtenstein", "lithuania", "latvia",
    "luxembourg", "monaco", "moldova", "montenegro", "malta",
    "netherlands", "norway", "poland", "portugal", "romania", "serbia",
    "sweden", "slovenia", "slovakia", "san marino", "turkey", "türkiye",
    "ukraine", "vatican", "kosovo", "germany", "alemania",
    "north macedonia", "russia",
}



def oportunidad_junior(oferta: Oferta) -> bool:
    tipo = (oferta.tipo or "").strip().lower()
    titulo = (oferta.titulo or "").lower()
    return tipo in TIPOS_JUNIOR or any(palabra in titulo for palabra in PALABRAS_JUNIOR)


# Abreviaturas postales de EE. UU. para formatos como "New York, NY".
# Son heurísticas: una abreviatura sola puede ser ambigua con países (CA, DE...).
ESTADOS_USA = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def region_oferta(ubicacion: str | None) -> str:
    """Devuelve 'elegible', 'revisar' o 'fuera'. No adivina Multiple Cities."""
    ubicacion = (ubicacion or "").strip()
    if not ubicacion:
        return "revisar"
    bajo = ubicacion.lower()
    if "multiple cit" in bajo or "various location" in bajo or "varias ciudad" in bajo:
        return "revisar"
    if "remote" in bajo and "," not in ubicacion and "europe" not in bajo:
        return "revisar"
    if "europe" in bajo or "europa" in bajo or "united states" in bajo or "usa" in bajo:
        return "elegible"

    ultimo = ubicacion.rsplit(",", 1)[-1].strip()
    codigo = ultimo.upper()
    if codigo == "US" or codigo in CODIGOS_EUROPA:
        return "elegible"
    # "Boston, MA", "San Francisco, CA", etc. El patrón puede ser ambiguo
    # cuando una abreviatura de estado coincide con un código de país.
    if "," in ubicacion and codigo in ESTADOS_USA:
        return "elegible"
    if ultimo.casefold() in {x.casefold() for x in NOMBRES_EUROPA}:
        return "elegible"
    # Sin país ni estado identificable, preferimos revisión a inventar región.
    return "fuera" if len(codigo) == 2 else "revisar"


def interes(oferta: Oferta) -> tuple[bool, str]:
    if SOLO_JUNIOR_Y_PRACTICAS and not oportunidad_junior(oferta):
        return False, ""
    region = region_oferta(oferta.ubicacion)
    if region == "elegible":
        return True, "Europa/EE. UU."
    if region == "revisar" and REVISAR_MULTICIUDAD:
        return True, "Ubicación por verificar"
    return False, ""


