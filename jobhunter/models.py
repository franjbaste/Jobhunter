"""Objetos que comparten todos los extractores de JobHunter."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Oferta:
    empresa: str
    job_id: str
    titulo: str
    ubicacion: str | None
    url: str
    tipo: str | None = None
    categoria: str | None = None


@dataclass(frozen=True, slots=True)
class ResultadoRastreo:
    empresa: str
    ofertas: list[Oferta]
    paginas: int
    repetidas: int = 0
    total_anunciado: int | None = None

    def validar(self) -> None:
        if not self.empresa.strip():
            raise ValueError("Resultado sin empresa")
        if self.paginas < 1:
            raise ValueError("El rastreo no terminó ninguna página/consulta")
        ids: set[str] = set()
        for oferta in self.ofertas:
            if oferta.empresa != self.empresa:
                raise ValueError("Una oferta pertenece a otra empresa")
            if not oferta.job_id or not oferta.titulo or not oferta.url:
                raise ValueError("Una oferta carece de ID, título o URL")
            if oferta.job_id in ids:
                raise ValueError(f"ID duplicado en el rastreo de {self.empresa}: {oferta.job_id}")
            ids.add(oferta.job_id)
