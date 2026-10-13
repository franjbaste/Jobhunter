"""Persistencia SQLite compartida por TODOS los scrapers.

Mantiene exactamente el esquema de IBM_monitor3.py. No hay migración ni
borrado de jobhunter.db: IBM conserva su estado y avisos anteriores.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from jobhunter.models import Oferta, ResultadoRastreo
from jobhunter.core.filters import interes


def utc_ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Cambios:
    primera_ejecucion: bool
    nuevas: list[Oferta]
    avisables: list[Oferta]


def preparar_bd(conexion: sqlite3.Connection) -> None:
    # Esquema de IBM_monitor3.py. Nunca eliminamos tablas ni filas antiguas.
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


def guardar_rastreo(conexion: sqlite3.Connection, resultado: ResultadoRastreo) -> Cambios:
    """Guarda el rastreo terminado; los errores de un scraper no modifican BD."""
    resultado.validar()
    empresa = resultado.empresa
    ahora = utc_ahora()

    con_estado = conexion.execute(
        "SELECT 1 FROM monitor_estado WHERE empresa = ?", (empresa,)
    ).fetchone() is not None
    anteriores = {
        fila[0] for fila in conexion.execute(
            "SELECT job_id FROM ofertas WHERE empresa = ?", (empresa,)
        )
    }
    nuevas = [o for o in resultado.ofertas if o.job_id not in anteriores]
    avisables = [o for o in nuevas if interes(o)[0]]

    with conexion:
        for o in resultado.ofertas:
            conexion.execute("""
                INSERT INTO ofertas
                  (empresa, job_id, titulo, categoria, tipo, ubicacion, url,
                   primera_vista, ultima_vista)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(empresa,job_id) DO UPDATE SET
                   titulo=excluded.titulo,
                   categoria=excluded.categoria,
                   tipo=excluded.tipo,
                   ubicacion=excluded.ubicacion,
                   url=excluded.url,
                   ultima_vista=excluded.ultima_vista
            """, (o.empresa, o.job_id, o.titulo, o.categoria, o.tipo,
                  o.ubicacion, o.url, ahora, ahora))

        if con_estado:
            for o in avisables:
                conexion.execute("""
                    INSERT OR IGNORE INTO alertas_pendientes(empresa, job_id, creada)
                    VALUES (?, ?, ?)
                """, (empresa, o.job_id, ahora))
            conexion.execute("""
                UPDATE monitor_estado
                   SET ultimo_rastreo_completo=?, paginas_revisadas=?
                 WHERE empresa=?
            """, (ahora, resultado.paginas, empresa))
        else:
            # Cada fuente define SU línea base inicial independiente.
            # Para IBM, al reutilizar su BD, con_estado ya es True.
            conexion.execute("""
                INSERT INTO monitor_estado
                  (empresa, primer_rastreo_completo,
                   ultimo_rastreo_completo, paginas_revisadas)
                VALUES (?, ?, ?, ?)
            """, (empresa, ahora, ahora, resultado.paginas))

    return Cambios(primera_ejecucion=not con_estado,
                   nuevas=nuevas, avisables=avisables)


def contar_pendientes(conexion: sqlite3.Connection, empresa: str) -> int:
    return conexion.execute("""
        SELECT COUNT(*) FROM alertas_pendientes
         WHERE empresa=? AND enviada IS NULL
    """, (empresa,)).fetchone()[0]
