
import requests
from bs4 import BeautifulSoup

url = url = "https://careers.ibm.com/en_US/careers/JobDetail?jobId=123797&source=WEB_Search_NA"
params = {
    "jobId": "123797",
    "source": "WEB_Search_NA"
}

# Descargamos el HTML
respuesta = requests.get(url, params=params, timeout=15)
print("Estado HTTP:", respuesta.status_code)
print("URL final:", respuesta.url)
print("Content-Type:", respuesta.headers.get("Content-Type"))
print("Tamaño HTML:", len(respuesta.text))
if respuesta.status_code != 200:
    raise RuntimeError(
        "PUTO ERROR"
    )

if not respuesta.content:
    raise RuntimeError(
        "IBM devolvió una respuesta vacía"
    )

# Interpretamos el HTML
soup = BeautifulSoup(respuesta.text, "html.parser")

print("\n--- ELEMENTOS ENCONTRADOS ---")

titulo = soup.select_one("h2.banner__text__title")
ubicacion = soup.select_one("span.card-item-location")
tipo = soup.select_one("span.card-item-type")

print("Título:", titulo.get_text(strip=True) if titulo else None)
print("Ubicación:", ubicacion.get_text(strip=True) if ubicacion else None)
print("Tipo:", tipo.get_text(strip=True) if tipo else None)

print("\n--- COMPROBACIÓN ---")
print("¿Aparece el título en HTML?",
      "TRANSITION MANAGER-FINANCE" in respuesta.text)

print("Título de la página:",
      soup.title.get_text(strip=True) if soup.title else None)
