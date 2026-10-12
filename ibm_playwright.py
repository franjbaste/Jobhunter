
import time
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)

URL_BASE = "https://www.ibm.com/careers/search"
MAX_PAGINAS = 3

ofertas = {}

with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    for numero_pagina in range(1, MAX_PAGINAS + 1):

        url = f"{URL_BASE}?p={numero_pagina}"

        print(f"\nConsultando página {numero_pagina}...")

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        enlaces = page.locator('a[href*="JobDetail"]')

        # Esperar a que aparezcan los resultados
        try:
            enlaces.first.wait_for(
                state="visible",
                timeout=20000
            )
        except PlaywrightTimeoutError:
            print("ERROR: No se cargaron las ofertas.")
            print("No podemos asumir que sea la última página.")
            break

        ofertas_pagina = {}

        for enlace in enlaces.all():

            href = enlace.get_attribute("href")

            if not href:
                continue

            url_completa = urljoin(page.url, href)

            parametros = parse_qs(
                urlparse(url_completa).query
            )

            job_id = parametros.get("jobId", [None])[0]

            if not job_id:
                continue

            categoria_elemento = enlace.locator(
                ".bx--card__eyebrow"
            )

            titulo_elemento = enlace.locator(
                ".bx--card__heading"
            )

            detalles_elemento = enlace.locator(
                ".ibm--card__copy__inner"
            )

            categoria = (
                categoria_elemento.inner_text().strip()
                if categoria_elemento.count() else None
            )

            titulo = (
                titulo_elemento.inner_text().strip()
                if titulo_elemento.count() else None
            )

            tipo = None
            ubicacion = None

            if detalles_elemento.count():

                lineas = detalles_elemento.inner_text().splitlines()
                lineas = [x.strip() for x in lineas if x.strip()]

                if len(lineas) >= 1:
                    tipo = lineas[0]

                if len(lineas) >= 2:
                    ubicacion = " ".join(lineas[1:])

            ofertas_pagina[job_id] = {
                "empresa": "IBM",
                "titulo": titulo,
                "categoria": categoria,
                "tipo": tipo,
                "ubicacion": ubicacion,
                "url": url_completa
            }

        # Comprobar que la página tiene ofertas nuevas
        nuevos_ids = set(ofertas_pagina) - set(ofertas)

        if not nuevos_ids:
            print("No se encontraron identificadores nuevos.")
            print("Revisar si la paginación ha funcionado.")
            break

        ofertas.update(ofertas_pagina)

        print("Ofertas en página:", len(ofertas_pagina))
        print("Ofertas nuevas:", len(nuevos_ids))
        print("Total acumulado:", len(ofertas))

        # Evitar peticiones demasiado seguidas
        time.sleep(2)

    browser.close()

print("\n--- RESULTADO FINAL ---")
print("Total de ofertas diferentes:", len(ofertas))

for job_id, oferta in ofertas.items():
    print(job_id, "|", oferta["titulo"], "|", oferta["tipo"])
