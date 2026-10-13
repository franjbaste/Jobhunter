

```bash
cd ~/Main/Jobhunter
cp jobhunter.db jobhunter.db.bak
unzip ~/Downloads/JobHunter_refactor.zip -d .
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py --listar
python3 -m unittest discover -s tests -v
python3 main.py --fuente IBM
```

Si guardaste el ZIP en otra ruta, sustituye `~/Downloads/` por la ruta correcta.
Este proyecto incluye `main.py` en la raíz; si ya tienes otro archivo `main.py`,
hazle copia primero.

**Importante:** el nuevo código utiliza el archivo
`~/Main/Jobhunter/jobhunter.db`. La fuente IBM sigue leyendo el estado
`monitor_estado` previo: no vuelve a considerar la primera ejecución como
línea base ni genera notificaciones masivas por el mero cambio de versión.

## Telegram

Se utilizan las mismas variables de entorno de la versión anterior:

```bash
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'
python3 main.py
```

Puedes dejarlas configuradas como ya hacías. No guardes el token en el código
ni lo subas a GitHub. Si no están configuradas, las alertas individuales
quedan pendientes en SQLite.

## Activar cualquier empresa que utilice Greenhouse

1. Identifica el **board token** real de su bolsa de empleo Greenhouse.
2. Abre `jobhunter/config.py` y cambia la configuración:

```python
GREENHOUSE_EMPRESAS = {
    "Empresa X": "token-real-empresa-x",
    "Empresa Y": "token-real-empresa-y",
}
```

Estos valores son marcadores de posición, **no empresas activas**. Necesitas
confirmar que cada portal utiliza Greenhouse y su token real. Cuando estén
configurados, ejecuta `python3 main.py --listar` para comprobar los nombres,
y luego `python3 main.py` para procesar IBM y los Greenhouse configurados.

También se puede ejecutar una empresa concreta:

```bash
python3 main.py --fuente IBM
python3 main.py --fuente 'Empresa X'
```

La API pública de Greenhouse devuelve todas las ofertas publicadas en una
respuesta JSON:
https://docs.greenhouse.io/job-board.html

## Estructura

```text
main.py                         # Ejecuta todas las fuentes
jobhunter/
  config.py                     # Fuentes y filtros
  models.py                     # Oferta y ResultadoRastreo
  runner.py                     # Orquestación
  core/
    database.py                 # SQLite compartida (esquema anterior)
    filters.py                  # Europa, EE. UU., junior y prácticas
    notifications.py            # Telegram, avisos pendientes y resumen
  scrapers/
    base.py                     # Interfaz abstracta
    ibm.py                      # Playwright + JSON, igual que IBM_monitor3
    greenhouse.py               # Reutilizable por board token
requirements.txt
tests/test_jobhunter.py
```

## Funcionamiento y límites

- **Cada empresa se distingue mediante la clave `(empresa, job_id)`**, de modo
  que dos empresas pueden usar el mismo ID sin colisionar.
- **Se guardan todas las vacantes encontradas**, sin filtrar por ubicación o
  experiencia. Los filtros solo controlan los avisos.
- **La primera ejecución completa de cada empresa nueva establece su línea
  base**. IBM reutiliza su línea base existente.
- Si un scraper falla, no se guarda su extracción parcial; se sigue con las
  demás empresas.
- Se conservan alertas pendientes cuando Telegram falla. Se envían hasta
  `MAX_AVISOS_INDIVIDUALES` por empresa y ejecución.
- **IBM:** se recorren todas las páginas anunciadas, pero el buscador puede
  modificar el orden de sus resultados durante el barrido y generar
  solapamientos. Una extracción finalizada no garantiza exhaustividad.
- **Greenhouse:** se prueba mediante mocks en las pruebas automatizadas. Se
  deberá verificar en vivo con un board token real antes de usarlo en
  producción.
- Las etiquetas de región se basan en texto/abreviaturas, no en geocodificación;
  las ubicaciones desconocidas pueden marcarse "por verificar".
- Comprueba y respeta las políticas de automatización de cada sitio, limita
  la frecuencia de consultas y no eludas controles de acceso.

## Comprobaciones realizadas

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```

Las pruebas cubren: migración sin pérdida de datos en el esquema existente,
líneas base independientes, deduplicación por empresa, filtros geográficos,
conservación de avisos fallidos y normalización de Greenhouse. No se ha
completado un barrido real de IBM en este entorno; esa validación se hace en
tu Mac.
