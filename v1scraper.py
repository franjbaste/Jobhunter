
import requests
from bs4 import BeautifulSoup

url = "https://realpython.github.io/fake-jobs/"

# 1. Solicitar el HTML
respuesta = requests.get(url, timeout=15)
respuesta.raise_for_status()

# 2. Interpretar el HTML
soup = BeautifulSoup(respuesta.text, "html.parser")

# 3. Encontrar todas las ofertas
ofertas = soup.select("div.card-content")

# 4. Extraer la información
for oferta in ofertas:
    titulo = oferta.select_one("h2.title")
    empresa = oferta.select_one("h3.company")
    ubicacion = oferta.select_one("p.location")

    nombre = titulo.get_text(strip = True)

    if "python" not in nombre.lower():
        continue



    if titulo and empresa and ubicacion:
        print("Puesto:", titulo.get_text(strip=True))
        print("Empresa:", empresa.get_text(strip=True))
        print("Ubicación:", ubicacion.get_text(strip=True))
        print("------------------------")
