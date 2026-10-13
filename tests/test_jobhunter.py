from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from jobhunter.models import Oferta, ResultadoRastreo
from jobhunter.core.database import preparar_bd, guardar_rastreo, contar_pendientes
from jobhunter.core.filters import region_oferta, interes
from jobhunter.core.notifications import enviar_pendientes
from jobhunter.scrapers.greenhouse import GreenhouseScraper
from jobhunter.scrapers.ibm import extraer_id


def oferta(empresa="IBM", job_id="1", titulo="Software Engineering Intern",
           ubicacion="Madrid, ES") -> Oferta:
    return Oferta(empresa=empresa, job_id=job_id, titulo=titulo,
                  ubicacion=ubicacion, url="https://example.com/jobs/" + job_id)


def scan(empresa, ofertas):
    return ResultadoRastreo(empresa=empresa, ofertas=ofertas, paginas=1)


class ModeloYFiltros(unittest.TestCase):
    def test_extraccion_id_ibm(self):
        self.assertEqual(extraer_id(
            "https://careers.ibm.com/en_US/careers/JobDetail?jobId=123754&source=WEB"
        ), "123754")

    def test_filtros_europa_estados_unidos(self):
        for ubicacion in ("Madrid, ES", "Paris, FR", "London, UK", "Berlin, DE",
                          "New York, NY", "San Francisco, CA", "Austin, TX",
                          "Boston, MA", "United States"):
            self.assertEqual(region_oferta(ubicacion), "elegible", ubicacion)
        self.assertEqual(region_oferta("Quezon City, PH"), "fuera")
        self.assertEqual(region_oferta("Toronto, ON"), "fuera")
        self.assertEqual(region_oferta("Multiple Cities"), "revisar")
        self.assertTrue(interes(oferta())[0])
        self.assertFalse(interes(oferta(titulo="Senior Manager"))[0])

    def test_no_aceptar_ids_duplicados_en_un_rastreo(self):
        with self.assertRaises(ValueError):
            scan("IBM", [oferta(job_id="1"), oferta(job_id="1")]).validar()


class CompatibilidadSQLite(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        preparar_bd(self.db)

    def tearDown(self):
        self.db.close()

    def test_compatibilidad_con_datos_anteriores_ibm(self):
        # Simula el esquema y el estado de IBM_monitor3 ya existentes.
        self.db.execute("""
            INSERT INTO monitor_estado
            VALUES ('IBM', '2026-10-01', '2026-10-12', 81)
        """)
        self.db.execute("""
            INSERT INTO ofertas VALUES
              ('IBM', '123', 'Oferta antigua', null, null, 'Madrid, ES',
               'https://example.com/123', '2026-10-01', '2026-10-12')
        """)
        self.db.commit()

        r = scan("IBM", [oferta(job_id="123"), oferta(job_id="456")])
        cambios = guardar_rastreo(self.db, r)
        self.assertFalse(cambios.primera_ejecucion)
        self.assertEqual([o.job_id for o in cambios.nuevas], ["456"])
        self.assertEqual(contar_pendientes(self.db, "IBM"), 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0], 2)

    def test_nueva_empresa_tiene_baseline_propia(self):
        nuevos = scan("Empresa X", [oferta(empresa="Empresa X", job_id="1")])
        cambios = guardar_rastreo(self.db, nuevos)
        self.assertTrue(cambios.primera_ejecucion)
        self.assertEqual(contar_pendientes(self.db, "Empresa X"), 0)
        cambios2 = guardar_rastreo(self.db, scan("Empresa X", [
            oferta(empresa="Empresa X", job_id="1"),
            oferta(empresa="Empresa X", job_id="2"),
        ]))
        self.assertFalse(cambios2.primera_ejecucion)
        self.assertEqual(contar_pendientes(self.db, "Empresa X"), 1)

    def test_mismo_id_en_empresas_distintas(self):
        guardar_rastreo(self.db, scan("IBM", [oferta(job_id="11")]))
        guardar_rastreo(self.db, scan("Empresa X", [oferta("Empresa X", job_id="11")]))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM ofertas WHERE job_id='11'"
        ).fetchone()[0], 2)

    def test_alertas_pendientes_se_conservan_si_telegram_falla(self):
        guardar_rastreo(self.db, scan("IBM", [oferta(job_id="1")]))
        guardar_rastreo(self.db, scan("IBM", [oferta(job_id="1"), oferta(job_id="2")]))
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "token-prueba",
            "TELEGRAM_CHAT_ID": "chat-prueba",
        }), patch("jobhunter.core.notifications.enviar_mensaje_telegram",
                  return_value=(False, "Prueba: error")):
            self.assertEqual(enviar_pendientes(self.db, "IBM"), 0)
        self.assertEqual(contar_pendientes(self.db, "IBM"), 1)


class Greenhouse(unittest.TestCase):
    def test_api_greenhouse_adaptada_a_modelo_comun(self):
        respuesta = MagicMock()
        respuesta.json.return_value = {"jobs": [
            {
                "id": 45, "title": "Software Engineering Intern",
                "location": {"name": "Madrid, Spain"},
                "absolute_url": "https://example.com/jobs/45",
                "departments": [{"name": "Engineering"}],
            },
            {
                "id": 46, "title": "Graduate Engineer",
                "location": {"name": "Boston, MA"},
                "absolute_url": "https://example.com/jobs/46",
            },
        ]}
        with patch("jobhunter.scrapers.greenhouse.requests.get", return_value=respuesta) as get:
            resultado = GreenhouseScraper("Empresa X", "un-token").obtener_ofertas()
        self.assertEqual(len(resultado.ofertas), 2)
        self.assertEqual(resultado.ofertas[0].categoria, "Engineering")
        self.assertEqual(resultado.ofertas[0].empresa, "Empresa X")
        self.assertEqual(resultado.ofertas[1].job_id, "46")
        self.assertTrue(interes(resultado.ofertas[1])[0])
        self.assertEqual(get.call_args.kwargs["params"], {"content": "true"})
        self.assertEqual(get.call_args.args[0],
                         "https://boards-api.greenhouse.io/v1/boards/un-token/jobs")


if __name__ == "__main__":
    unittest.main()
