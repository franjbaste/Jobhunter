
import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise RuntimeError(
        "Falta configurar TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID"
    )

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

respuesta = requests.post(
    url,
    json={
        "chat_id": CHAT_ID,
        "text": "🚀 JobHunter conectado correctamente con Telegram."
    },
    timeout=15
)

datos = respuesta.json()

if respuesta.ok and datos.get("ok"):
    print("Mensaje enviado correctamente.")
else:
    print("Error de Telegram:", datos.get("description"))
