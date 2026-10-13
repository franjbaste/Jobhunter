"""Extractor configurable para bolsas de trabajo públicas Greenhouse.

Documentación del proveedor:
https://docs.greenhouse.io/job-board.html
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
"""
from __future__ import annotations

from urllib.parse import quote
import requests
from jobhunter.models import Oferta, ResultadoRastreo
from jobhunter.scrapers.base import BaseScraper


class GreenhouseScraper(BaseScraper):
    def __init__(self, empresa: str, board_token: str):
        if not empresa.strip() or not board_token.strip():
            raise ValueError("Indica nombre de empresa y token de Greenhouse")
        self.empresa = empresa
        self.board_token = board_token

    def obtener_ofertas(self) -> ResultadoRastreo:
        url = ("https://boards-api.greenhouse.io/v1/boards/"
               + quote(self.board_token, safe="") + "/jobs")
        # Solo GET público; no se necesitan credenciales para los job boards.
        respuesta = requests.get(url, params={"content": "true"}, timeout=35)
        respuesta.raise_for_status()
        datos = respuesta.json()
        if not isinstance(datos, dict) or not isinstance(datos.get("jobs"), list):
            raise RuntimeError(f"Respuesta Greenhouse inesperada para {self.empresa}")

        ofertas: list[Oferta] = []
        for job in datos["jobs"]:
            if not isinstance(job, dict):
                raise RuntimeError("Greenhouse devolvió un registro no válido")
            identificador = job.get("id")
            titulo = job.get("title")
            enlace = job.get("absolute_url")
            if identificador is None or not titulo or not enlace:
                raise RuntimeError(f"Registro Greenhouse incompleto: {self.empresa}")

            ubicacion = job.get("location") or {}
            categoria = job.get("departments") or []
            ofertas.append(Oferta(
                empresa=self.empresa,
                job_id=str(identificador),
                titulo=str(titulo),
                ubicacion=ubicacion.get("name") if isinstance(ubicacion, dict) else None,
                url=str(enlace),
                # Greenhouse no define un campo universal 'internship'; el
                # filtro de junior también revisará el título.
                tipo=None,
                categoria=(str(categoria[0].get("name"))
                           if categoria and isinstance(categoria[0], dict) else None),
            ))

        resultado = ResultadoRastreo(
            empresa=self.empresa,
            ofertas=ofertas,
            paginas=1,  # un endpoint entrega la colección completa
            total_anunciado=len(ofertas),
        )
        resultado.validar()
        return resultado
