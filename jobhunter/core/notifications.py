"""Notificaciones reutilizables: IBM, Greenhouse y futuras fuentes."""
from __future__ import annotations

import os
import sqlite3
import time

import requests

from jobhunter.config import MAX_AVISOS_INDIVIDUALES
from jobhunter.core.database import contar_pendientes, utc_ahora, Cambios
from jobhunter.core.filters import interes, region_oferta
from jobhunter.models import ResultadoRastreo


def enviar_mensaje_telegram(texto: str) -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": texto[:4000]},
            timeout=20,
        )
        r.raise_for_status()
        if r.json().get("ok"):
            return True, ""
        return False, "Telegram no confirmó el envío"
    except (requests.RequestException, ValueError, TypeError) as exc:
        # No mostramos la URL de la petición: contiene el token secreto.
        return False, f"Error de Telegram: {type(exc).__name__}"


def enviar_pendientes(conexion: sqlite3.Connection, empresa: str) -> int:
    pendientes = contar_pendientes(conexion, empresa)
    print(f"[{empresa}] Avisos pendientes antes del envío: {pendientes}")
    if not pendientes:
        return 0
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        print("[Telegram] Sin configurar: se mantienen pendientes en SQLite")
        return 0

    filas = conexion.execute("""
        SELECT o.job_id, o.titulo, o.tipo, o.ubicacion, o.url
          FROM alertas_pendientes a
          JOIN ofertas o ON o.empresa=a.empresa AND o.job_id=a.job_id
         WHERE a.empresa=? AND a.enviada IS NULL
         ORDER BY a.creada, o.job_id
         LIMIT ?
    """, (empresa, MAX_AVISOS_INDIVIDUALES)).fetchall()

    enviados = 0
    for job_id, titulo, tipo, ubicacion, url in filas:
        mensaje = (
            f"🆕 {empresa} · oportunidad detectada por primera vez por JobHunter\n"
            f"{titulo}\n"
            f"{tipo or 'Tipo desconocido'} · {ubicacion or 'Ubicación desconocida'}\n"
            f"{url}"
        )
        if region_oferta(ubicacion) == "revisar":
            mensaje = "⚠️ Ubicación por verificar\n" + mensaje
        ok, error = enviar_mensaje_telegram(mensaje)
        if not ok:
            print(f"[Telegram] No enviada {empresa}/{job_id}: {error}")
            break
        with conexion:
            conexion.execute("""
                UPDATE alertas_pendientes SET enviada=?
                 WHERE empresa=? AND job_id=?
            """, (utc_ahora(), empresa, job_id))
        enviados += 1
        print(f"[Telegram] Enviada: {empresa}/{job_id} · {titulo}")
        time.sleep(0.2)
    print(f"[{empresa}] Avisos enviados: {enviados}; "
          f"pendientes: {contar_pendientes(conexion, empresa)}")
    return enviados


def resumen_rastreo(resultado: ResultadoRastreo, cambios: Cambios,
                    enviados: int, pendientes: int) -> str:
    texto_estado = ("Línea base inicial guardada (sin alertas antiguas)"
                    if cambios.primera_ejecucion
                    else "Comparación con SQLite finalizada")
    return (
        f"🤖 JobHunter · {resultado.empresa}\n\n"
        f"✅ {texto_estado}\n"
        f"📄 Páginas/consultas recorridas: {resultado.paginas}\n"
        f"🔎 Ofertas únicas observadas: {len(resultado.ofertas)}\n"
        f"🔁 Apariciones repetidas: {resultado.repetidas}\n"
        f"📥 IDs no vistos antes en SQLite: {len(cambios.nuevas)}\n"
        f"🌍 Nuevos IDs que cumplen filtros: {len(cambios.avisables)}\n"
        f"📨 Alertas individuales enviadas: {enviados}\n"
        f"⏳ Alertas pendientes: {pendientes}\n\n"
        "ℹ️ Primera aparición en el monitor no significa necesariamente "
        "publicación reciente. La cobertura puede ser incompleta si el "
        "portal reordena sus resultados."
    )
