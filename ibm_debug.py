
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse, parse_qs

URL = "https://www.ibm.com/careers/search?p=1"


def obtener_ids(page):

    enlaces = page.locator('a[href*="JobDetail"]')

    urls = enlaces.evaluate_all(
        "(elementos) => elementos.map(e => e.href)"
    )

    ids = set()

    for url in urls:

        parametros = parse_qs(urlparse(url).query)
        job_id = parametros.get("jobId", [None])[0]

        if job_id:
            ids.add(job_id)

    return ids


with sync_playwright() as p:

    # 1. Abrir navegador
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    try:
        # 2. Cargar primera página
        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=30000
        )

        enlaces = page.locator('a[href*="JobDetail"]')
        enlaces.first.wait_for(timeout=20000)

        ids_anteriores = obtener_ids(page)

        print("Página 1:", len(ids_anteriores), "ofertas")

        # 3. Esperar respuesta de la API de IBM
        with page.expect_response(
            lambda r: (
                urlparse(r.url).path == "/search/api/v2"
                and r.status == 200
            ),
            timeout=30000
        ) as respuesta_evento:

            page.locator(
                'a.cds--pagination-nav__page'
                '[aria-label="Page 2"]'
            ).click()

        respuesta_api = respuesta_evento.value

        print("\nRespuesta del buscador recibida.")

        # 4. INVESTIGAR LA API
        print("\n--- INVESTIGANDO LA API ---")

        print("URL:", respuesta_api.url.split("?")[0])
        print("Estado:", respuesta_api.status)
        print(
            "Content-Type:",
            respuesta_api.headers.get("content-type")
        )

        try:
            datos = respuesta_api.json()

            if isinstance(datos, dict):

                print("\n--- INFORMACIÓN DE LA BÚSQUEDA ---")

                print("Claves principales:", list(datos.keys()))
                print("Tiempo:", datos.get("took"), "ms")
                print("Timeout:", datos.get("timed_out"))

                # 5. Analizar hits
                hits = datos.get("hits", {})

                if isinstance(hits, dict):

                    print("\n--- ESTRUCTURA DE HITS ---")

                    print("Claves:", list(hits.keys()))
                    print("Total:", hits.get("total"))

                    resultados = hits.get("hits", [])

                    if isinstance(resultados, list):

                        print(
                            "Resultados recibidos:",
                            len(resultados)
                        )

                        # 6. Inspeccionar el primer resultado
                        if resultados:

                            primer_resultado = resultados[0]

                            if isinstance(primer_resultado, dict):

                                print("\n--- PRIMER RESULTADO ---")

                                print(
                                    "Claves:",
                                    list(primer_resultado.keys())
                                )

                                print(
                                    "ID interno:",
                                    primer_resultado.get("_id")
                                )

                                # 7. Analizar _source
                                contenido = primer_resultado.get(
                                    "_source"
                                )

                                if isinstance(contenido, dict):

                                    print(
                                        "\n--- CAMPOS DEL DOCUMENTO ---"
                                    )

                                    print(list(contenido.keys()))

                                else:
                                    print(
                                        "Tipo de _source:",
                                        type(contenido).__name__
                                    )

                    else:
                        print("hits.hits no es una lista")

                else:
                    print("Estructura de hits inesperada")

            else:
                print(
                    "Tipo de respuesta:",
                    type(datos).__name__
                )

        except Exception as error:
            print(
                "Error al analizar JSON:",
                type(error).__name__,
                str(error)
            )

        # 8. Esperar a que el DOM muestre página 2
        page.wait_for_function(
            """(anteriores) => {

                const activa = document.querySelector(
                    ".cds--pagination-nav__page--active"
                );

                const enlaces = Array.from(
                    document.querySelectorAll(
                        'a[href*="JobDetail"]'
                    )
                );

                const ids = enlaces.map(
                    e => new URL(e.href).searchParams.get("jobId")
                ).filter(Boolean);

                const actual = [...new Set(ids)].sort();
                const previo = [...anteriores].sort();

                return (
                    activa?.getAttribute("data-key") === "2"
                    && ids.length === 30
                    && JSON.stringify(actual) !== JSON.stringify(previo)
                );

            }""",
            arg=list(ids_anteriores),
            timeout=20000
        )

        # 9. Obtener IDs de página 2
        ids_nuevos = obtener_ids(page)

        print("\n--- RESULTADOS DE PAGINACIÓN ---")

        print("Página 2:", len(ids_nuevos), "ofertas")

        print(
            "IDs repetidos:",
            len(ids_nuevos & ids_anteriores)
        )

        print(
            "Rango:",
            page.locator(
                ".ibm--pagination__totalresults"
            ).inner_text()
        )

        print(
            "Total de ofertas únicas:",
            len(ids_anteriores | ids_nuevos)
        )

    finally:
        # 10. Cerrar navegador
        browser.close()
