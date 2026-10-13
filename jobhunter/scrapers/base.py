from __future__ import annotations
from abc import ABC, abstractmethod
from jobhunter.models import ResultadoRastreo


class BaseScraper(ABC):
    empresa: str

    @abstractmethod
    def obtener_ofertas(self) -> ResultadoRastreo:
        """Devuelve un rastreo verificado o lanza excepción; no escribe en SQLite."""
        raise NotImplementedError
