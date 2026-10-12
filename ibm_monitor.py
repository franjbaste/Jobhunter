"""Monitor de IBM para JobHunter.

Prototipo basado en la estructura observada en octubre de 2026.
Antes de ejecutar rastreos recurrentes, comprueba las condiciones de IBM
(y las reglas robots.txt) para las rutas utilizadas.
"""

import math
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

URL_BUSCADOR = "https://www.ibm.com/careers/search"
RUTA_BD = "jobhunter.db"
MAX_PAGINAS = 3  # Prueba inicial; NO equivale a buscar todas las ofertas.
ESPERA_ENTRE_PAGINAS = 3
TIPOS_INTERESANTES = {"internship", "entry level"}


def extraer_id(url):
    parsed = urlparse(url)
    identificador = parse_qs(parsed.query).get("jobId", [None])[0]
    if identificador:
        return identificador
    # IBM también utiliza URLs canónicas: /JobDetail/Nombre-del-puesto/12345
    match = re.search(r"/JobDetail/[^/?]+/(\d+)(?:/|$)", parsed.path)
    return match.group(1) if match else None


def obtener_resultados_api(respuesta):
    datos = respuesta.json()
    if not isinstance(datos, dict) or datos.get("timed_out"):
        raise RuntimeError("La API no devolvió una búsqueda válida")
    bloque = datos.get("hits", {})
    hits = bloque.get("hits", []) if isinstance(bloque, dict) else None
    if not isinstance(hits, list) or not hits:
        raise RuntimeError("La respuesta de IBM no contiene resultados")
    total = bloque.get("total", {})
    total = total.get("value") if isinstance(total, dict) else total
    return hits, total


def esperar_tarjetas_correctas(pagina, numero, hits):
    """Verifica que el DOM corresponda al JSON, no a la página anterior."""
    fuentes = [h.get("_source", {}) for h in hits]
    urls = [fuente.get("url", "") for fuente in fuentes]
    ids_api = [extraer_id(url) for url in urls]
    titulos_api = [fuente.get("title") for fuente in fuentes]

    if all(ids_api) and len(set(ids_api)) == len(hits):
        modo, esperados = "ids", ids_api
    elif all(isinstance(t, str) and t.strip() for t in titulos_api):
        modo, esperados = "titulos", titulos_api
    else:
        raise RuntimeError(
            "No puedo contrastar la API con las tarjetas: "
            "revisa los valores de _source.url y _source.title"
        )

    pagina.wait_for_function(
        r"""({numero, modo, esperados}) => {
            const activo = document.querySelector(
                '.cds--pagination-nav__page--active'
            );
            if (activo?.getAttribute('data-key') !== String(numero))
                return false;

            const links = [...document.querySelectorAll('a[href*="JobDetail"]')];
            if (links.length !== esperados.length) return false;
            let actual;
            if (modo === 'ids') {
                actual = links.map(a => new URL(a.href).searchParams.get('jobId'));
            } else {
                actual = links.map(a => a.querySelector('.bx--card__heading')?.textContent);
            }
            const normalizar = x => String(x ?? '').trim()
                .replace(/\s+/g, ' ').toLowerCase();
            return JSON.stringify(actual.map(normalizar).sort()) ===
                   JSON.stringify(esperados.map(normalizar).sort());
        }""",
        arg={"numero": numero, "modo": modo, "esperados": esperados},
        timeout=20000,
    )


def extraer_tarjetas(pagina):
    ofertas = {}
    links = pagina.locator('a[href*="JobDetail"]')
    for link in links.all():
        href = link.get_attribute("href")
        if not href:
            continue
        url = urljoin(pagina.url, href)
        identificador = extraer_id(url)
        titulo_tag = link.locator(".bx--card__heading")
        if not identificador or not titulo_tag.count():
            continue

        categoria_tag = link.locator(".bx--card__eyebrow")
        detalle_tag = link.locator(".ibm--card__copy__inner")
        detalles = (
            [linea.strip() for linea in detalle_tag.inner_text().splitlines()
             if linea.strip()]
            if detalle_tag.count() else []
        )
        ofertas[identificador] = {
            "job_id": identificador,
            "empresa": "IBM",
            "titulo": titulo_tag.inner_text().strip(),
            "categoria": categoria_tag.inner_text().strip() if categoria_tag.count() else None,
            "tipo": detalles[0] if detalles else None,
            "ubicacion": " ".join(detalles[1:]) if len(detalles) > 1 else None,
            "url": url,
        }
    return ofertas


def rastrear_ibm():
    acumuladas = {}
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page()
        try:
            for numero in range(1, MAX_PAGINAS + 1):
                url = f"{URL_BUSCADOR}?p={numero}"
                print(f"Consultando página {numero}: {url}")

                # Registramos la espera ANTES de navegar para no perder la respuesta.
                with pagina.expect_response(
                    lambda r: (
                        urlparse(r.url).path == "/search/api/v2"
                        and r.status == 200
                    ),
                    timeout=30000,
                ) as evento:
                    pagina.goto(url, wait_until="domcontentloaded", timeout=30000)

                hits, total = obtener_resultados_api(evento.value)
                esperar_tarjetas_correctas(pagina, numero, hits)
                ofertas_pagina = extraer_tarjetas(pagina)

                if len(ofertas_pagina) != len(hits):
                    raise RuntimeError(
                        f"Página {numero} incompleta: "
                        f"{len(ofertas_pagina)} tarjetas frente a {len(hits)} hits"
                    )

                nuevas_en_esta_pagina = set(ofertas_pagina) - set(acumuladas)
                acumuladas.update(ofertas_pagina)
                print(f"  {len(ofertas_pagina)} ofertas; "
                      f"{len(nuevas_en_esta_pagina)} IDs aún no vistos en esta ejecución")

                if isinstance(total, int) and numero >= math.ceil(total / 30):
                    break
                if len(hits) < 30:
                    break
                time.sleep(ESPERA_ENTRE_PAGINAS)
        finally:
            navegador.close()
    return acumuladas


def guardar_y_detectar_nuevas(ofertas):
    with sqlite3.connect(RUTA_BD) as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS ofertas (
                empresa TEXT NOT NULL,
                job_id TEXT NOT NULL,
                titulo TEXT NOT NULL,
                categoria TEXT,
                tipo TEXT,
                ubicacion TEXT,
                url TEXT NOT NULL,
                primera_vista TEXT NOT NULL,
                ultima_vista TEXT NOT NULL,
                PRIMARY KEY (empresa, job_id)
            )
        """)
        existentes = {
            row[0] for row in conexion.execute(
                "SELECT job_id FROM ofertas WHERE empresa = 'IBM'"
            )
        }
        primera_ejecucion = len(existentes) == 0
        nuevas = [oferta for ident, oferta in ofertas.items() if ident not in existentes]
        ahora = datetime.now(timezone.utc).isoformat()

        for oferta in ofertas.values():
            conexion.execute("""
                INSERT INTO ofertas (
                    empresa, job_id, titulo, categoria, tipo, ubicacion,
                    url, primera_vista, ultima_vista
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(empresa, job_id) DO UPDATE SET
                    titulo=excluded.titulo,
                    categoria=excluded.categoria,
                    tipo=excluded.tipo,
                    ubicacion=excluded.ubicacion,
                    url=excluded.url,
                    ultima_vista=excluded.ultima_vista
            """, (
                oferta["empresa"], oferta["job_id"], oferta["titulo"],
                oferta["categoria"], oferta["tipo"], oferta["ubicacion"],
                oferta["url"], ahora, ahora,
            ))
    return primera_ejecucion, nuevas


def enviar_telegram(ofertas):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not ofertas:
        return

    texto = "Nuevas oportunidades IBM:\n\n" + "\n\n".join(
        f"{o['titulo']} ({o['tipo']})\n{o['ubicacion']}\n{o['url']}"
        for o in ofertas[:8]
    )
    if len(ofertas) > 8:
        texto += f"\n\nY {len(ofertas) - 8} más (consulta la terminal)."

    respuesta = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": texto[:4000]},
        timeout=15,
    )
    respuesta.raise_for_status()
    print("Notificación enviada por Telegram")


def main():
    # Primero rastreamos todo el rango configurado; si falla alguna página,
    # NO escribimos datos incompletos en SQLite.
    ofertas = rastrear_ibm()
    if not ofertas:
        raise RuntimeError("No se pudieron verificar ofertas de IBM")

    primera, nuevas = guardar_y_detectar_nuevas(ofertas)
    relevantes = [
        o for o in nuevas
        if (o["tipo"] or "").strip().lower() in TIPOS_INTERESANTES
    ]
    print(f"\nOfertas únicas verificadas: {len(ofertas)}")
    print(f"Nuevas respecto a SQLite: {len(nuevas)}")
    print(f"Nuevas Internship / Entry Level: {len(relevantes)}")
    for oferta in relevantes:
        print(f"  - {oferta['titulo']} | {oferta['ubicacion']}\n    {oferta['url']}")

    if primera:
        print("Primera ejecución: creada línea base; sin notificaciones")
    else:
        enviar_telegram(relevantes)


if __name__ == "__main__":
    main()
