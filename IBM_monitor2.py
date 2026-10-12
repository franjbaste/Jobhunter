"""JobHunter: monitor de vacantes de IBM.

Lee los resultados que el buscador público muestra mediante Playwright y valida
las tarjetas frente a la respuesta JSON que recibe el navegador. Recorre todas
las páginas comunicadas por la primera consulta.

Requiere: pip install playwright requests
          python -m playwright install chromium

Consulta y respeta las condiciones de uso/robots.txt de las fuentes antes de
realizar comprobaciones automatizadas frecuentes; no elude controles de acceso.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

# ======================= CONFIGURACIÓN ========================
URL_BUSCADOR = "https://www.ibm.com/careers/search"
BASE_DATOS = Path(__file__).with_name("jobhunter.db")
MOSTRAR_NAVEGADOR = False  # Cambiar a False cuando esté validado en tu Mac
SEGUNDOS_ENTRE_PAGINAS = 3
INTENTOS_POR_PAGINA = 2
TIMEOUT_MS = 30_000

# Se guardan TODAS las vacantes en SQLite. Estos filtros afectan a las ALERTAS.
SOLO_JUNIOR_Y_PRACTICAS = True
REVISAR_MULTICIUDAD = True  # Avisa como "por verificar", sin afirmar ubicación

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


# ======================= EXTRACCIÓN ===========================
def utc_ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


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


# ======================= FILTROS ==============================
def oportunidad_junior(oferta: dict) -> bool:
    tipo = (oferta.get("tipo") or "").strip().lower()
    titulo = (oferta.get("titulo") or "").lower()
    return tipo in TIPOS_JUNIOR or any(palabra in titulo for palabra in PALABRAS_JUNIOR)


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
    if ultimo.casefold() in {x.casefold() for x in NOMBRES_EUROPA}:
        return "elegible"
    # Evitar interpretar 'CA' (Canadá) como California.
    return "fuera" if len(codigo) == 2 else "revisar"


def interes(oferta: dict) -> tuple[bool, str]:
    if SOLO_JUNIOR_Y_PRACTICAS and not oportunidad_junior(oferta):
        return False, ""
    region = region_oferta(oferta.get("ubicacion"))
    if region == "elegible":
        return True, "Europa/EE. UU."
    if region == "revisar" and REVISAR_MULTICIUDAD:
        return True, "Ubicación por verificar"
    return False, ""


# ======================= SQLITE ===============================
def preparar_bd(conexion):
    conexion.executescript("""
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
    );
    CREATE TABLE IF NOT EXISTS monitor_estado (
        empresa TEXT PRIMARY KEY,
        primer_rastreo_completo TEXT NOT NULL,
        ultimo_rastreo_completo TEXT NOT NULL,
        paginas_revisadas INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alertas_pendientes (
        empresa TEXT NOT NULL,
        job_id TEXT NOT NULL,
        creada TEXT NOT NULL,
        enviada TEXT,
        PRIMARY KEY (empresa, job_id),
        FOREIGN KEY (empresa, job_id) REFERENCES ofertas(empresa, job_id)
    );
    """)


def guardar_y_preparar_avisos(conexion, ofertas: dict, paginas: int):
    """Actualización atómica, solo tras completar todas las páginas."""
    ahora = utc_ahora()
    con_estado = conexion.execute(
        "SELECT 1 FROM monitor_estado WHERE empresa = ?", ("IBM",)
    ).fetchone() is not None
    anteriores = {
        fila[0] for fila in conexion.execute(
            "SELECT job_id FROM ofertas WHERE empresa = ?", ("IBM",)
        )
    }
    nuevas = [o for job_id, o in ofertas.items() if job_id not in anteriores]
    avisables = [o for o in nuevas if interes(o)[0]]

    with conexion:
        for oferta in ofertas.values():
            conexion.execute("""
                INSERT INTO ofertas
                    (empresa,job_id,titulo,categoria,tipo,ubicacion,url,primera_vista,ultima_vista)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(empresa,job_id) DO UPDATE SET
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
        if con_estado:
            for oferta in avisables:
                conexion.execute("""
                    INSERT OR IGNORE INTO alertas_pendientes(empresa,job_id,creada)
                    VALUES (?,?,?)
                """, ("IBM", oferta["job_id"], ahora))
            conexion.execute("""
                UPDATE monitor_estado
                SET ultimo_rastreo_completo=?, paginas_revisadas=?
                WHERE empresa='IBM'
            """, (ahora, paginas))
        else:
            # La BD puede tener pruebas anteriores de 3 páginas. El primer
            # rastreo COMPLETO establece una línea base sin alertas masivas.
            conexion.execute("""
                INSERT INTO monitor_estado
                    (empresa,primer_rastreo_completo,ultimo_rastreo_completo,paginas_revisadas)
                VALUES ('IBM',?,?,?)
            """, (ahora, ahora, paginas))

    return not con_estado, nuevas, avisables


# ======================= AVISOS ===============================
def enviar_pendientes(conexion):
    pendientes = conexion.execute("""
        SELECT o.job_id,o.titulo,o.tipo,o.ubicacion,o.url
        FROM alertas_pendientes a
        JOIN ofertas o ON o.empresa=a.empresa AND o.job_id=a.job_id
        WHERE a.empresa='IBM' AND a.enviada IS NULL
        ORDER BY a.creada,o.job_id
    """).fetchall()

    print(f"Avisos pendientes: {len(pendientes)}")
    if not pendientes:
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram no configurado. Las alertas quedan pendientes en SQLite.")
        return

    # Una notificación por oferta; se marca enviada solo tras confirmar Telegram.
    for job_id, titulo, tipo, ubicacion, url in pendientes:
        texto = (
            f"🆕 IBM · nueva oportunidad detectada\n"
            f"{titulo}\n{tipo or 'Tipo desconocido'} · {ubicacion or 'Ubicación desconocida'}\n"
            f"{url}"
        )
        if region_oferta(ubicacion) == "revisar":
            texto = "⚠️ Ubicación por verificar\n" + texto
        try:
            respuesta = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": texto[:4000]},
                timeout=20,
            )
            respuesta.raise_for_status()
            if not respuesta.json().get("ok"):
                raise RuntimeError("Telegram no confirmó el envío")
            with conexion:
                conexion.execute("""
                    UPDATE alertas_pendientes SET enviada=?
                    WHERE empresa='IBM' AND job_id=?
                """, (utc_ahora(), job_id))
            print(f"  [Telegram] Enviada: {job_id} · {titulo}")
        except Exception as exc:
            print(f"  [Telegram] No enviada {job_id}: {type(exc).__name__}: {exc}")
            print("  Aviso conservado para reintentar la próxima ejecución")
            break


def main():
    print("JobHunter · IBM · barrido de todas las páginas")
    print("Ubicaciones: Europa y Estados Unidos (+ multiciudad por revisar)")
    print("Avisos junior/prácticas:", SOLO_JUNIOR_Y_PRACTICAS)

    # Solo se escribe en BD después de que el rastreo termine correctamente.
    ofertas, paginas, repetidas = rastrear_ibm()
    if not ofertas:
        raise RuntimeError("No se han podido verificar ofertas")

    with sqlite3.connect(BASE_DATOS) as conexion:
        preparar_bd(conexion)
        primera, nuevas, avisables = guardar_y_preparar_avisos(
            conexion, ofertas, paginas
        )
        print("\n---------- RESUMEN ----------")
        print("Páginas recorridas:", paginas)
        print("Ofertas únicas extraídas:", len(ofertas))
        print("Apariciones repetidas entre páginas:", repetidas)
        if repetidas:
            print("Aviso: IBM puede reordenar ofertas durante el barrido; "
                  "no es posible garantizar exhaustividad absoluta.")
        print("Identificadores no vistos antes en SQLite:", len(nuevas))
        print("Nuevas que cumplen filtros:", len(avisables))

        if primera:
            print("PRIMER RASTREO COMPLETO: línea base guardada sin avisar.")
        else:
            for oferta in avisables[:25]:
                _, etiqueta = interes(oferta)
                print(f"  [{etiqueta}] {oferta['titulo']} | "
                      f"{oferta['ubicacion']}\n  {oferta['url']}")
            if len(avisables) > 25:
                print(f"  ...y {len(avisables)-25} más en SQLite")

        enviar_pendientes(conexion)
        print(f"BD guardada en: {BASE_DATOS}")


if __name__ == "__main__":
    main()
