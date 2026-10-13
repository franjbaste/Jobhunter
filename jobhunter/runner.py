"""Orquestación multiempresa: extraer -> filtrar -> SQLite -> Telegram."""
from __future__ import annotations

import sqlite3
from jobhunter import config
from jobhunter.core.database import preparar_bd, guardar_rastreo, contar_pendientes
from jobhunter.core.filters import interes
from jobhunter.core.notifications import (
    enviar_pendientes, enviar_mensaje_telegram, resumen_rastreo,
)
from jobhunter.scrapers.base import BaseScraper
from jobhunter.scrapers.ibm import IBMScraper
from jobhunter.scrapers.greenhouse import GreenhouseScraper


def crear_scrapers() -> list[BaseScraper]:
    scrapers: list[BaseScraper] = [IBMScraper()]
    for nombre, token in config.GREENHOUSE_EMPRESAS.items():
        scrapers.append(GreenhouseScraper(nombre, token))
    nombres = [s.empresa for s in scrapers]
    if len(set(nombres)) != len(nombres):
        raise ValueError("Dos scrapers tienen el mismo nombre de empresa")
    return scrapers


def procesar_scraper(scraper: BaseScraper) -> bool:
    empresa = scraper.empresa
    print(f"\n=== {empresa} ===")
    try:
        resultado = scraper.obtener_ofertas()
        # No se guardan rastreos parciales: el adaptador debe terminar completo.
        resultado.validar()
    except Exception as exc:
        print(f"[{empresa}] RASTREO FALLIDO: {type(exc).__name__}: {exc}")
        ok, error = enviar_mensaje_telegram(
            f"⚠️ JobHunter · {empresa}: rastreo interrumpido. "
            f"No se guardó un barrido parcial. Motivo: {type(exc).__name__}"
        )
        if not ok:
            print(f"[Telegram] Error al avisar del fallo: {error}")
        return False

    with sqlite3.connect(config.BASE_DATOS) as conexion:
        preparar_bd(conexion)
        cambios = guardar_rastreo(conexion, resultado)
        print("Páginas/consultas:", resultado.paginas)
        print("Ofertas únicas:", len(resultado.ofertas))
        print("Repetidas entre páginas:", resultado.repetidas)
        print("IDs no vistos antes:", len(cambios.nuevas))
        print("Nuevas que cumplen filtros:", len(cambios.avisables))
        if cambios.primera_ejecucion:
            print(f"[{empresa}] Primera línea base guardada, sin avisos antiguos")
        else:
            for oferta in cambios.avisables[:25]:
                _, etiqueta = interes(oferta)
                print(f"  [{etiqueta}] {oferta.titulo} | "
                      f"{oferta.ubicacion}\n  {oferta.url}")
            if len(cambios.avisables) > 25:
                print(f"  ...y {len(cambios.avisables)-25} más en SQLite")
        enviados = enviar_pendientes(conexion, empresa)
        pendientes = contar_pendientes(conexion, empresa)
        ok, error = enviar_mensaje_telegram(
            resumen_rastreo(resultado, cambios, enviados, pendientes)
        )
        if ok:
            print(f"[Telegram] Resumen {empresa} enviado")
        else:
            print(f"[Telegram] No se pudo enviar resumen {empresa}: {error}")
    print("BD:", config.BASE_DATOS)
    return True
