"""Extractor de IBM. Mantiene la lógica Playwright+JSON del monitor validado.

Puede haber páginas solapadas si IBM reordena resultados durante el barrido.
Recorre todas las páginas anunciadas, pero no garantiza exhaustividad absoluta.
"""
from __future__ import annotations

import math
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse
from playwright.sync_api import sync_playwright
from jobhunter.config import (
    URL_BUSCADOR, MOSTRAR_NAVEGADOR, SEGUNDOS_ENTRE_PAGINAS,
    INTENTOS_POR_PAGINA, TIMEOUT_MS,
)
from jobhunter.models import Oferta, ResultadoRastreo
from jobhunter.scrapers.base import BaseScraper

def extraer_id(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    partes = urlparse(url)
    identificador = parse_qs(partes.query).get("jobId", [None])[0]
    if identificador:
        return str(identificador)
    coincidencia = re.search(r"/JobDetail/[^/?]+/(\d+)(?:/|$)", partes.path)
    return coincidencia.group(1) if coincidencia else None


def extraer_hits(respuesta):
    datos = respuesta.json()
    if not isinstance(datos, dict) or datos.get("timed_out"):
        raise RuntimeError("La búsqueda JSON falló o expiró")
    bloque = datos.get("hits")
    if not isinstance(bloque, dict) or not isinstance(bloque.get("hits"), list):
        raise RuntimeError("IBM cambió la estructura JSON de la búsqueda")
    hits = bloque["hits"]
    total = bloque.get("total")
    total = total.get("value") if isinstance(total, dict) else total
    if not isinstance(total, int) or total < 0:
        raise RuntimeError("IBM no devolvió el total de resultados")
    return hits, total


def esperar_tarjetas_de_la_api(pagina, numero: int, hits: list):
    """No leer tarjetas antiguas: validar rango y contenido frente al JSON."""
    fuentes = [hit.get("_source") or {} for hit in hits]
    ids_api = [extraer_id(fuente.get("url")) for fuente in fuentes]
    titulos_api = [fuente.get("title") for fuente in fuentes]

    if ids_api and all(ids_api) and len(set(ids_api)) == len(ids_api):
        modo, esperados = "ids", ids_api
    elif all(isinstance(t, str) and t.strip() for t in titulos_api):
        modo, esperados = "titulos", titulos_api
    else:
        raise RuntimeError(
            "No se puede contrastar el JSON con el HTML: inspecciona "
            "_source.url y _source.title antes de continuar"
        )

    pagina.wait_for_function(
        r"""({numero, tam, modo, esperados}) => {
          const activo = document.querySelector('.cds--pagination-nav__page--active');
          const contador = document.querySelector('.ibm--pagination__totalresults');
          if (!activo || !contador) return false;
          if (activo.getAttribute('data-key') !== String(numero)) return false;
          const rango = (contador.textContent || '').match(
            /(\d+)\s*[-–—]\s*(\d+)\s+of\s+[\d,]+\s+items/i
          );
          if (!rango || Number(rango[1]) !== (numero - 1) * tam + 1) return false;
          const tarjetas = [...document.querySelectorAll('a[href*="JobDetail"]')];
          if (tarjetas.length !== esperados.length) return false;
          const actual = (modo === 'ids')
            ? tarjetas.map(a => new URL(a.href).searchParams.get('jobId'))
            : tarjetas.map(a => a.querySelector('.bx--card__heading')?.textContent);
          const norm = x => String(x ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
          const ordenar = xs => xs.map(norm).sort();
          return JSON.stringify(ordenar(actual)) === JSON.stringify(ordenar(esperados));
        }""",
        arg={"numero": numero, "tam": 30, "modo": modo, "esperados": esperados},
        timeout=TIMEOUT_MS,
    )


def extraer_tarjetas(pagina) -> dict[str, dict]:
    # Extraemos en una sola operación sobre el DOM para evitar decenas de
    # llamadas remotas a Playwright por cada página.
    elementos = pagina.locator('a[href*="JobDetail"]').evaluate_all(
        """links => links.map(a => ({
          href: a.href,
          titulo: a.querySelector('.bx--card__heading')?.innerText?.trim() || '',
          categoria: a.querySelector('.bx--card__eyebrow')?.innerText?.trim() || null,
          detalles: a.querySelector('.ibm--card__copy__inner')?.innerText || ''
        }))"""
    )
    ofertas = {}
    for elem in elementos:
        enlace = urljoin(pagina.url, elem["href"])
        job_id = extraer_id(enlace)
        titulo = elem["titulo"]
        if not job_id or not titulo:
            raise RuntimeError("Tarjeta sin jobId o título: cambió el HTML de IBM")
        lineas = [x.strip() for x in elem["detalles"].splitlines() if x.strip()]
        ofertas[job_id] = {
            "empresa": "IBM", "job_id": job_id, "titulo": titulo,
            "categoria": elem["categoria"],
            "tipo": lineas[0] if lineas else None,
            "ubicacion": " ".join(lineas[1:]) if len(lineas) > 1 else None,
            "url": enlace,
        }
    if len(ofertas) != len(elementos):
        raise RuntimeError("Una página contiene IDs duplicados o inválidos")
    return ofertas


def rastrear_ibm() -> tuple[dict[str, dict], int, int]:
    """Visita las páginas 1..N; si una falla, NO actualiza SQLite."""
    todas = {}
    repetidas_entre_paginas = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not MOSTRAR_NAVEGADOR)
        contexto = browser.new_context()
        try:
            pagina_actual = 1
            paginas_totales = None
            total_inicial = None

            while paginas_totales is None or pagina_actual <= paginas_totales:
                url = f"{URL_BUSCADOR}?p={pagina_actual}"
                errores = []
                print(f"[IBM] Página {pagina_actual}"
                      + (f"/{paginas_totales}" if paginas_totales else ""))

                for intento in range(1, INTENTOS_POR_PAGINA + 1):
                    pagina = contexto.new_page()
                    try:
                        # Captura la respuesta ANTES de navegar, para no perderla.
                        with pagina.expect_response(
                            lambda r: urlparse(r.url).path == "/search/api/v2" and r.status == 200,
                            timeout=TIMEOUT_MS,
                        ) as evento:
                            pagina.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

                        hits, total_actual = extraer_hits(evento.value)
                        if pagina_actual == 1:
                            if total_actual == 0:
                                raise RuntimeError("IBM devolvió cero vacantes; verificar buscador")
                            if not hits:
                                raise RuntimeError("La primera página no devolvió hits")
                            total_inicial = total_actual
                            paginas_totales = math.ceil(total_inicial / len(hits))
                            print(f"[IBM] Total anunciado: {total_inicial}; "
                                  f"páginas que recorrer: {paginas_totales}")
                        if not hits:
                            raise RuntimeError(f"Página {pagina_actual} vacía inesperadamente")

                        esperar_tarjetas_de_la_api(pagina, pagina_actual, hits)
                        ofertas_pagina = extraer_tarjetas(pagina)
                        if len(ofertas_pagina) != len(hits):
                            raise RuntimeError(
                                f"Página incompleta: {len(ofertas_pagina)} tarjetas "
                                f"frente a {len(hits)} resultados de la API"
                            )

                        repetidas = len(set(ofertas_pagina) & set(todas))
                        repetidas_entre_paginas += repetidas
                        todas.update(ofertas_pagina)
                        print(f"  Extraídas: {len(ofertas_pagina)} | "
                              f"Repetidas: {repetidas} | Únicas: {len(todas)}")
                        if total_actual != total_inicial:
                            print(f"  Aviso: el total cambió de {total_inicial} a {total_actual}")
                        break

                    except Exception as exc:
                        errores.append(f"intento {intento}: {type(exc).__name__}: {exc}")
                        if intento < INTENTOS_POR_PAGINA:
                            print("  Reintentando esta página...")
                            time.sleep(5)
                    finally:
                        if not pagina.is_closed():
                            pagina.close()
                else:
                    raise RuntimeError(
                        f"No se pudo verificar la página {pagina_actual}. "
                        "No se guardará un rastreo incompleto. " + " | ".join(errores)
                    )

                pagina_actual += 1
                if paginas_totales and pagina_actual <= paginas_totales:
                    time.sleep(SEGUNDOS_ENTRE_PAGINAS)
        finally:
            contexto.close()
            browser.close()

    return todas, paginas_totales or 0, repetidas_entre_paginas


class IBMScraper(BaseScraper):
    empresa = "IBM"

    def obtener_ofertas(self) -> ResultadoRastreo:
        datos, paginas, repetidas = rastrear_ibm()
        ofertas = [Oferta(**dato) for dato in datos.values()]
        resultado = ResultadoRastreo(
            empresa=self.empresa,
            ofertas=ofertas,
            paginas=paginas,
            repetidas=repetidas,
        )
        resultado.validar()
        return resultado
